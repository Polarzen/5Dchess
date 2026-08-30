"""Local CPU/CUDA training CLI for the candidate Policy/Value network."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Sequence

import torch
from torch.utils.data import DataLoader, Subset

from src.training.checkpoint import load_checkpoint, load_resume_state, save_checkpoint
from src.training.config import TrainConfig, model_preset
from src.training.dataset import ShardedDataset, collate_training_batch, split_indices
from src.training.model import PolicyValueModel, policy_value_loss
from src.training.utils import print_device_report, resolve_device, seed_everything


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
):
    training = optimizer is not None
    model.train(training)
    totals = {"policy_loss": 0.0, "value_loss": 0.0, "total_loss": 0.0, "policy_accuracy": 0.0}
    samples = 0
    batches = 0
    started = time.perf_counter()
    context = torch.enable_grad if training else torch.no_grad
    with context():
        for raw_batch in loader:
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
    elapsed = max(1e-9, time.perf_counter() - started)
    if samples == 0:
        return {**totals, "samples": 0, "samples_per_second": 0.0, "elapsed_seconds": elapsed}
    return {
        **{key: value / samples for key, value in totals.items()},
        "samples": samples,
        "batches": batches,
        "samples_per_second": samples / elapsed,
        "elapsed_seconds": elapsed,
    }


def train_local(
    *,
    dataset_path: str | Path,
    output: str | Path,
    epochs: int,
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
) -> dict:
    seed_everything(seed)
    device = resolve_device(device_name)
    print_device_report(device_name)
    dataset = ShardedDataset(dataset_path)
    train_indices, validation_indices = split_indices(len(dataset), validation_fraction, seed)

    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    history_path = output / "history.jsonl"

    start_epoch = 0
    global_step = 0
    best_validation_loss = float("inf")
    if resume is not None:
        model, metadata = load_checkpoint(resume, device=device)
        print(f"resuming model from {Path(resume).resolve()}")
        start_epoch = int(metadata.get("epoch", 0))
        global_step = int(metadata.get("global_step", 0))
        stored_best = metadata.get("best_validation_loss")
        if stored_best is not None:
            best_validation_loss = float(stored_best)
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

    final_record = None
    for epoch in range(start_epoch + 1, epochs + 1):
        train_metrics = _run_loader(
            model,
            train_loader,
            device=device,
            optimizer=optimizer,
            scaler=scaler,
            value_weight=value_weight,
            grad_clip=grad_clip,
            use_amp=use_amp,
        )
        global_step += int(train_metrics.get("batches", 0))
        if validation_loader is not None:
            validation_metrics = _run_loader(
                model,
                validation_loader,
                device=device,
                optimizer=None,
                scaler=None,
                value_weight=value_weight,
                grad_clip=grad_clip,
                use_amp=use_amp,
            )
            validation_loss = float(validation_metrics["total_loss"])
        else:
            validation_metrics = None
            validation_loss = float(train_metrics["total_loss"])
        scheduler.step()

        record = {
            "epoch": epoch,
            "global_step": global_step,
            "lr": float(optimizer.param_groups[0]["lr"]),
            "train": train_metrics,
            "validation": validation_metrics,
            "validation_loss": validation_loss,
        }
        _append_history(history_path, record)
        print(json.dumps(record, sort_keys=True))

        if epoch % max(1, save_every) == 0:
            save_checkpoint(
                output / "last",
                model,
                epoch=epoch,
                global_step=global_step,
                seed=seed,
                best_validation_loss=min(best_validation_loss, validation_loss),
                training_config=training_config,
                optimizer=optimizer,
                scheduler=scheduler,
            )
        if validation_loss <= best_validation_loss:
            best_validation_loss = validation_loss
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

    if final_record is None:
        raise ValueError(
            f"target epochs ({epochs}) must be greater than resume epoch ({start_epoch})"
        )
    return {
        "output": str(output),
        "device": str(device),
        "parameters": model.parameter_count,
        "best_validation_loss": best_validation_loss,
        "last_epoch": final_record["epoch"],
        "global_step": global_step,
    }


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
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
