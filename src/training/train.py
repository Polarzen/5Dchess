"""Local CPU/CUDA training CLI for the candidate Policy/Value network."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time
from typing import Sequence

import torch
from torch.utils.data import DataLoader, Subset

from src.training.checkpoint import load_checkpoint, load_resume_state, save_checkpoint
from src.training.config import TrainConfig, model_preset
from src.training.dataset import ShardedDataset, collate_training_batch, split_indices
from src.training.model import PolicyValueModel, policy_value_loss
from src.training.utils import print_device_report, resolve_device, seed_everything, write_json


def _validate_wall_seconds(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("max_wall_seconds must be a non-negative number or null")
    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError("max_wall_seconds must be a finite non-negative number")
    return value


def _to_device(batch, device):
    return {
        key: value.to(device, non_blocking=device.type == "cuda")
        for key, value in batch.items()
        if torch.is_tensor(value)
    }


def _append_history(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _run_loader(
    model,
    loader,
    *,
    device,
    optimizer=None,
    scaler=None,
    value_weight: float,
    grad_clip: float,
    use_amp: bool,
    should_stop=None,
):
    training = optimizer is not None
    model.train(training)
    totals = {"policy_loss": 0.0, "value_loss": 0.0, "total_loss": 0.0, "policy_accuracy": 0.0}
    samples = 0
    batches = 0
    started = time.perf_counter()
    stopped = False
    context = torch.enable_grad if training else torch.no_grad
    with context():
        for raw_batch in loader:
            # Check only at batch boundaries: a batch already handed to the
            # model is allowed to finish and leave a valid optimizer state.
            if should_stop is not None and should_stop():
                stopped = True
                break
            batch = _to_device(raw_batch, device)
            batch_size = int(batch["selected_index"].shape[0])
            if training:
                optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(
                device_type=device.type,
                enabled=bool(use_amp and device.type == "cuda"),
            ):
                logits, value = model(
                    batch["state_boards"],
                    batch["board_meta"],
                    batch["board_mask"],
                    batch["state_global"],
                    batch["action_moves"],
                    batch["action_move_mask"],
                    batch["action_global"],
                    batch["candidate_mask"],
                )
                loss, metrics = policy_value_loss(
                    logits,
                    value,
                    batch["selected_index"],
                    batch["value_target"],
                    batch["value_mask"],
                    value_weight=value_weight,
                )
            if training:
                if scaler is not None and scaler.is_enabled():
                    scaler.scale(loss).backward()
                    scaler.unscale_(optimizer)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
                    optimizer.step()
            for key in totals:
                totals[key] += float(metrics[key].item()) * batch_size
            samples += batch_size
            batches += 1
            if should_stop is not None and should_stop():
                stopped = True
                break
    elapsed = max(1e-9, time.perf_counter() - started)
    if samples == 0:
        return {
            **totals,
            "samples": 0,
            "batches": 0,
            "samples_per_second": 0.0,
            "elapsed_seconds": elapsed,
            "stopped": stopped,
        }
    return {
        **{key: value / samples for key, value in totals.items()},
        "samples": samples,
        "batches": batches,
        "samples_per_second": samples / elapsed,
        "elapsed_seconds": elapsed,
        "stopped": stopped,
    }


def train_local(
    *,
    dataset_path: str | Path,
    output: str | Path,
    epochs: int | None = None,
    batch_size: int,
    lr: float,
    weight_decay: float,
    device_name: str,
    seed: int,
    num_workers: int,
    resume: str | Path | None,
    save_every: int,
    grad_clip: float,
    mixed_precision: bool,
    validation_fraction: float,
    value_weight: float,
    preset: str,
    max_wall_seconds: float | None = None,
    target_epochs: int | None = None,
    cloud_resume: bool = False,
) -> dict:
    if target_epochs is not None:
        if epochs is not None and int(epochs) != int(target_epochs):
            raise ValueError("epochs and target_epochs disagree")
        epochs = target_epochs
    if epochs is None:
        raise ValueError("epochs (the total target) is required")
    if isinstance(epochs, bool) or not isinstance(epochs, int) or epochs < 1:
        raise ValueError("epochs must be a positive integer total target")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    max_wall_seconds = _validate_wall_seconds(max_wall_seconds)
    if cloud_resume and resume is None:
        raise ValueError("cloud_resume requires an explicit resume checkpoint")
    # Accept the cloud-facing signed seed contract while satisfying NumPy's
    # unsigned seed requirement.
    seed_everything(int(seed) % (2**32))
    device = resolve_device(device_name)
    print_device_report(device_name)
    dataset = ShardedDataset(dataset_path)
    train_indices, validation_indices = split_indices(
        len(dataset), validation_fraction, int(seed) % (2**32)
    )

    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    history_path = output / "history.jsonl"

    start_epoch = 0
    global_step = 0
    best_validation_loss = float("inf")
    best_epoch = 0
    if resume is not None:
        model, metadata = load_checkpoint(
            resume,
            device=device,
        )
        if cloud_resume:
            resume_preset = str(metadata["model_config"]["preset"]).lower()
            if resume_preset != str(preset).lower():
                raise ValueError(
                    f"cloud resume model preset {resume_preset!r} does not match requested {preset!r}"
                )
        print(f"resuming model from {Path(resume).resolve()}")
        start_epoch = int(metadata.get("epoch", 0))
        global_step = int(metadata.get("global_step", 0))
        stored_best = metadata.get("best_validation_loss")
        if stored_best is not None:
            best_validation_loss = float(stored_best)
            best_epoch = start_epoch
    else:
        model = PolicyValueModel(model_preset(preset))
        model.to(device)

    print(f"model preset: {model.model_config.preset}")
    print(f"model parameters: {model.parameter_count:,}")
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=lr, weight_decay=weight_decay
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=max(1, epochs)
    )
    if resume is not None:
        resume_epoch, resume_step = load_resume_state(
            resume,
            optimizer=optimizer,
            scheduler=scheduler,
            device=device,
        )
        start_epoch = max(start_epoch, resume_epoch)
        global_step = max(global_step, resume_step)
        # The previous scheduler was created for the previous total target.
        # Preserve its trusted state/base LR while extending the cosine
        # horizon to this invocation's new total target; otherwise a run that
        # reached its old target would resume at a permanently zero LR.
        scheduler.T_max = max(1, epochs)
        scheduler.last_epoch = start_epoch
        resumed_lrs = [
            scheduler.eta_min
            + (base_lr - scheduler.eta_min)
            * (1.0 + math.cos(math.pi * start_epoch / scheduler.T_max))
            / 2.0
            for base_lr in scheduler.base_lrs
        ]
        for group, resumed_lr in zip(optimizer.param_groups, resumed_lrs):
            group["lr"] = float(resumed_lr)
        scheduler._last_lr = [float(value) for value in resumed_lrs]
    if start_epoch >= epochs:
        raise ValueError(
            f"target epochs ({epochs}) must be greater than resume epoch ({start_epoch})"
        )
    initial_step = int(global_step)

    train_loader = DataLoader(
        Subset(dataset, train_indices),
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        collate_fn=collate_training_batch,
        pin_memory=device.type == "cuda",
    )
    validation_loader = None
    if validation_indices:
        validation_loader = DataLoader(
            Subset(dataset, validation_indices),
            batch_size=batch_size,
            shuffle=False,
            num_workers=num_workers,
            collate_fn=collate_training_batch,
            pin_memory=device.type == "cuda",
        )

    use_amp = bool(mixed_precision and device.type == "cuda")
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    training_config = TrainConfig(
        epochs=epochs,
        batch_size=batch_size,
        lr=lr,
        weight_decay=weight_decay,
        value_weight=value_weight,
        validation_fraction=validation_fraction,
        seed=seed,
        num_workers=num_workers,
        grad_clip=grad_clip,
        mixed_precision=mixed_precision,
        save_every=save_every,
    ).to_dict()
    training_config["preset"] = model.model_config.preset
    training_config["target_epochs"] = int(epochs)
    training_config["max_wall_seconds"] = max_wall_seconds
    training_config["cloud_resume"] = bool(cloud_resume)

    # Keep a portable run description.  In particular, do not persist the
    # caller's absolute dataset path: cloud resume receives its dataset path
    # from the new workflow invocation and must not depend on an old runner's
    # filesystem layout.
    write_json(
        output / "run-config.json",
        {
            "training_config": training_config,
            "start_epoch": int(start_epoch),
            "start_step": int(global_step),
            "resumed": resume is not None,
        },
    )

    started = time.monotonic()
    deadline = (
        None
        if max_wall_seconds is None
        else started + float(max_wall_seconds)
    )

    def budget_expired() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    def save_last(epoch: int, best_loss: float | None) -> None:
        save_checkpoint(
            output / "last",
            model,
            epoch=max(0, int(epoch)),
            global_step=global_step,
            seed=seed,
            best_validation_loss=best_loss,
            training_config=training_config,
            optimizer=optimizer,
            scheduler=scheduler,
        )

    final_record = None
    stop_reason = "completed"
    end_epoch = start_epoch
    # Every cloud artifact has a predictable best/ directory, even when the
    # first epoch is longer than the remaining wall budget.  On a resume this
    # is the validated incoming model at its completed epoch.
    if not (output / "best" / "model.safetensors").is_file():
        save_checkpoint(
            output / "best",
            model,
            epoch=start_epoch,
            global_step=global_step,
            seed=seed,
            best_validation_loss=(
                None if math.isinf(best_validation_loss) else best_validation_loss
            ),
            training_config=training_config,
            optimizer=optimizer,
            scheduler=scheduler,
        )
    for epoch in range(start_epoch + 1, epochs + 1):
        if budget_expired():
            stop_reason = "wall_time_budget"
            final_record = {
                "epoch": int(start_epoch),
                "global_step": int(global_step),
                "lr": float(optimizer.param_groups[0]["lr"]),
                "train": None,
                "validation": None,
                "validation_loss": None,
                "stop_reason": stop_reason,
                "partial_epoch": False,
            }
            _append_history(history_path, final_record)
            break
        train_metrics = _run_loader(
            model,
            train_loader,
            device=device,
            optimizer=optimizer,
            scaler=scaler,
            value_weight=value_weight,
            grad_clip=grad_clip,
            use_amp=use_amp,
            should_stop=budget_expired,
        )
        global_step += int(train_metrics.get("batches", 0))
        if train_metrics.get("stopped"):
            stop_reason = "wall_time_budget"
            record = {
                # The partially processed epoch is deliberately not marked
                # complete.  Resume repeats it from its dataset boundary while
                # retaining the valid optimizer/model progress already made.
                "epoch": end_epoch,
                "attempted_epoch": epoch,
                "global_step": global_step,
                "lr": float(optimizer.param_groups[0]["lr"]),
                "train": train_metrics,
                "validation": None,
                "validation_loss": float(train_metrics["total_loss"]),
                "stop_reason": stop_reason,
                "partial_epoch": True,
            }
            _append_history(history_path, record)
            final_record = record
            break
        if validation_loader is not None and not budget_expired():
            validation_metrics = _run_loader(
                model,
                validation_loader,
                device=device,
                optimizer=None,
                scaler=None,
                value_weight=value_weight,
                grad_clip=grad_clip,
                use_amp=use_amp,
                should_stop=budget_expired,
            )
            if validation_metrics.get("stopped"):
                stop_reason = "wall_time_budget"
                validation_loss = float(train_metrics["total_loss"])
                validation_metrics = None
            else:
                validation_loss = float(validation_metrics["total_loss"])
        elif validation_loader is not None:
            stop_reason = "wall_time_budget"
            validation_metrics = None
            validation_loss = float(train_metrics["total_loss"])
        else:
            validation_metrics = None
            validation_loss = float(train_metrics["total_loss"])
        if stop_reason != "wall_time_budget":
            scheduler.step()

        if stop_reason == "completed" and epoch < epochs and budget_expired():
            stop_reason = "wall_time_budget"

        record = {
            "epoch": epoch,
            "global_step": global_step,
            "lr": float(optimizer.param_groups[0]["lr"]),
            "train": train_metrics,
            "validation": validation_metrics,
            "validation_loss": validation_loss,
            "stop_reason": stop_reason,
        }
        if stop_reason == "wall_time_budget":
            record["partial_epoch"] = False
        _append_history(history_path, record)
        print(json.dumps(record, sort_keys=True))

        if epoch % max(1, save_every) == 0:
            save_last(epoch, min(best_validation_loss, validation_loss))
        if stop_reason != "wall_time_budget" and validation_loss <= best_validation_loss:
            best_validation_loss = validation_loss
            best_epoch = epoch
            save_checkpoint(
                output / "best",
                model,
                epoch=epoch,
                global_step=global_step,
                seed=seed,
                best_validation_loss=best_validation_loss,
                training_config=training_config,
                optimizer=optimizer,
                scheduler=scheduler,
            )
        final_record = record
        end_epoch = epoch
        if stop_reason == "wall_time_budget":
            break

    training_config["stop_reason"] = stop_reason
    if final_record is None:
        # A zero-length budget can expire before the first batch.  Publish a
        # valid epoch/step-zero checkpoint so a later invocation can resume
        # safely, while still treating the bounded stop as successful.
        if stop_reason == "wall_time_budget":
            save_last(start_epoch, None if math.isinf(best_validation_loss) else best_validation_loss)
        else:
            raise ValueError(
                f"target epochs ({epochs}) must be greater than resume epoch ({start_epoch})"
            )
    else:
        # The final checkpoint is unconditional.  This intentionally repeats a
        # periodic save when save_every divides the target, keeping the
        # published ``last`` artifact correct for all stop paths.
        save_last(end_epoch, None if math.isinf(best_validation_loss) else best_validation_loss)

    elapsed = max(0.0, time.monotonic() - started)
    result = {
        "output": str(output),
        "device": str(device),
        "parameters": model.parameter_count,
        "best_validation_loss": (
            None if math.isinf(best_validation_loss) else best_validation_loss
        ),
        "best_epoch": int(best_epoch),
        "start_epoch": int(start_epoch),
        "end_epoch": int(end_epoch),
        "start_step": int(initial_step),
        "end_step": int(global_step),
        "last_epoch": int(end_epoch),
        "global_step": global_step,
        "stop_reason": stop_reason,
        "elapsed_seconds": elapsed,
        "metrics": final_record,
    }
    write_json(output / "training-summary.json", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train Local AI candidate policy/value model")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--save-every", type=int, default=1)
    parser.add_argument("--grad-clip", type=float, default=1.0)
    parser.add_argument("--mixed-precision", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--validation-fraction", type=float, default=0.05)
    parser.add_argument("--value-weight", type=float, default=0.5)
    parser.add_argument("--preset", choices=["tiny", "small", "medium"], default="small")
    parser.add_argument(
        "--max-wall-seconds",
        type=float,
        default=None,
        help="stop at a safe epoch/batch boundary (default: unlimited)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = train_local(
        dataset_path=args.dataset,
        output=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        weight_decay=args.weight_decay,
        device_name=args.device,
        seed=args.seed,
        num_workers=args.num_workers,
        resume=args.resume,
        save_every=args.save_every,
        grad_clip=args.grad_clip,
        mixed_precision=args.mixed_precision,
        validation_fraction=args.validation_fraction,
        value_weight=args.value_weight,
        preset=args.preset,
        max_wall_seconds=args.max_wall_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
