"""Tiny end-to-end training smoke: generate -> train -> reload -> arena."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
from typing import Sequence

import torch

from src.ai.action_planner import ActionSearchBudget
from src.training.arena import evaluate_arena
from src.training.checkpoint import load_checkpoint
from src.training.config import PlannerConfig
from src.training.dataset import ShardedDataset, collate_training_batch
from src.training.selfplay import generate_selfplay
from src.training.train import train_local
from src.training.utils import resolve_device, seed_everything


def run_smoke(*, device_name: str = "cpu", work_dir: str | Path | None = None) -> dict:
    seed = 123
    seed_everything(seed)
    if work_dir is None:
        context = tempfile.TemporaryDirectory(prefix="5dchess-training-smoke-")
        root = Path(context.name)
    else:
        context = None
        root = Path(work_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)

    try:
        dataset_dir = root / "dataset"
        run_dir = root / "run"
        generated = generate_selfplay(
            games=2,
            teacher="easy",
            output=dataset_dir,
            seed=seed,
            max_actions=2,
            planner_config=PlannerConfig(
                max_states=64,
                max_actions=4,
                max_move_depth=4,
                max_seconds=0.25,
            ),
            shard_size=8,
            deterministic_planner=True,
        )
        if generated["sample_count"] < 2:
            raise RuntimeError("smoke self-play produced too few samples")

        trained = train_local(
            dataset_path=dataset_dir,
            output=run_dir,
            epochs=2,
            batch_size=2,
            lr=1e-3,
            weight_decay=0.0,
            device_name=device_name,
            seed=seed,
            num_workers=0,
            resume=None,
            save_every=1,
            grad_clip=1.0,
            mixed_precision=False,
            validation_fraction=0.25,
            value_weight=0.5,
            preset="tiny",
        )

        device = resolve_device(device_name)
        model_a, meta_a = load_checkpoint(run_dir / "best", device=device)
        model_b, meta_b = load_checkpoint(run_dir / "best", device=device)
        sample = ShardedDataset(dataset_dir)[0]
        batch = collate_training_batch([sample])
        batch = {key: value.to(device) for key, value in batch.items() if torch.is_tensor(value)}
        model_a.eval()
        model_b.eval()
        with torch.inference_mode():
            out_a = model_a(
                batch["state_boards"], batch["board_meta"], batch["board_mask"],
                batch["state_global"], batch["action_moves"], batch["action_move_mask"],
                batch["action_global"], batch["candidate_mask"],
            )
            out_b = model_b(
                batch["state_boards"], batch["board_meta"], batch["board_mask"],
                batch["state_global"], batch["action_moves"], batch["action_move_mask"],
                batch["action_global"], batch["candidate_mask"],
            )
        reload_match = bool(
            torch.allclose(out_a[0], out_b[0], rtol=1e-6, atol=1e-7)
            and torch.allclose(out_a[1], out_b[1], rtol=1e-6, atol=1e-7)
        )
        if not reload_match:
            raise RuntimeError("checkpoint reload changed logits/value")

        arena = evaluate_arena(
            checkpoint=run_dir / "best",
            opponent="easy",
            games=2,
            device_name=device_name,
            seed=321,
            max_actions=2,
            budget=ActionSearchBudget(
                max_states=64,
                max_actions=4,
                max_move_depth=4,
                max_seconds=0.25,
            ),
        )
        if arena["illegal_action_count"] or arena["stale_failure_count"]:
            raise RuntimeError("arena produced an illegal or stale Action")
        result = {
            "work_dir": str(root),
            "samples": generated["sample_count"],
            "epochs": trained["last_epoch"],
            "parameters": trained["parameters"],
            "best_validation_loss": trained["best_validation_loss"],
            "checkpoint_epoch": meta_a["epoch"],
            "checkpoint_reload_match": reload_match,
            "arena": arena,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return result
    finally:
        if context is not None:
            context.cleanup()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Local AI Training v2 tiny smoke")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="cpu")
    parser.add_argument("--work-dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_smoke(device_name=args.device, work_dir=args.work_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
