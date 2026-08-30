"""Versioned safetensors checkpoints plus explicit trusted resume state."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import torch
from safetensors.torch import load_file, save_file

from src.training.config import (
    ACTION_ENCODING_VERSION,
    CHECKPOINT_FORMAT_VERSION,
    DATASET_SCHEMA_VERSION,
    ENGINE_BASELINE_SHA,
    STATE_ENCODING_VERSION,
    EncodingConfig,
    ModelConfig,
)
from src.training.model import PolicyValueModel
from src.training.utils import read_json, write_json


class CheckpointFormatError(ValueError):
    pass


def _metadata(
    *,
    model_config: ModelConfig,
    encoding_config: EncodingConfig,
    epoch: int,
    global_step: int,
    seed: int,
    best_validation_loss: float | None,
    training_config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "checkpoint_format_version": CHECKPOINT_FORMAT_VERSION,
        "state_encoding_version": STATE_ENCODING_VERSION,
        "action_encoding_version": ACTION_ENCODING_VERSION,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "engine_baseline_sha": ENGINE_BASELINE_SHA,
        "model_config": asdict(model_config),
        "encoding_config": asdict(encoding_config),
        "epoch": int(epoch),
        "global_step": int(global_step),
        "seed": int(seed),
        "best_validation_loss": (
            None if best_validation_loss is None else float(best_validation_loss)
        ),
        "training_config": dict(training_config),
    }


def validate_checkpoint_metadata(metadata: dict[str, Any]) -> None:
    expected = {
        "checkpoint_format_version": CHECKPOINT_FORMAT_VERSION,
        "state_encoding_version": STATE_ENCODING_VERSION,
        "action_encoding_version": ACTION_ENCODING_VERSION,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise CheckpointFormatError(
                f"{key}={metadata.get(key)!r} is incompatible; expected {value!r}"
            )


def save_checkpoint(
    directory: str | Path,
    model: PolicyValueModel,
    *,
    epoch: int,
    global_step: int,
    seed: int,
    best_validation_loss: float | None,
    training_config: dict[str, Any],
    optimizer=None,
    scheduler=None,
) -> Path:
    directory = Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    weights_path = directory / "model.safetensors"
    cpu_state = {name: tensor.detach().cpu().contiguous() for name, tensor in model.state_dict().items()}
    save_file(cpu_state, str(weights_path))
    metadata = _metadata(
        model_config=model.model_config,
        encoding_config=model.encoding_config,
        epoch=epoch,
        global_step=global_step,
        seed=seed,
        best_validation_loss=best_validation_loss,
        training_config=training_config,
    )
    write_json(directory / "metadata.json", metadata)
    if optimizer is not None:
        # This file uses torch.save/pickle only for a user-created local resume
        # state.  Loading it is intentionally opt-in via --resume.
        resume = {
            "epoch": int(epoch),
            "global_step": int(global_step),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict() if scheduler is not None else None,
        }
        torch.save(resume, directory / "resume_state.pt")
    return directory


def load_checkpoint(
    directory: str | Path,
    *,
    device="cpu",
) -> tuple[PolicyValueModel, dict[str, Any]]:
    directory = Path(directory).expanduser().resolve()
    metadata = read_json(directory / "metadata.json")
    validate_checkpoint_metadata(metadata)
    model_config = ModelConfig(**metadata["model_config"])
    encoding_config = EncodingConfig(**metadata["encoding_config"])
    model = PolicyValueModel(model_config, encoding_config)
    state = load_file(str(directory / "model.safetensors"), device=str(device))
    model.load_state_dict(state, strict=True)
    model.to(device)
    return model, metadata


def load_resume_state(
    directory: str | Path,
    *,
    optimizer,
    scheduler=None,
    device="cpu",
) -> tuple[int, int]:
    """Load an explicitly requested, locally trusted optimizer resume file."""
    directory = Path(directory).expanduser().resolve()
    path = directory / "resume_state.pt"
    if not path.exists():
        raise FileNotFoundError(f"resume state not found: {path}")
    try:
        state = torch.load(path, map_location=device, weights_only=False)
    except TypeError:
        state = torch.load(path, map_location=device)
    optimizer.load_state_dict(state["optimizer"])
    if scheduler is not None and state.get("scheduler") is not None:
        scheduler.load_state_dict(state["scheduler"])
    return int(state["epoch"]), int(state["global_step"])


__all__ = [
    "CheckpointFormatError",
    "load_checkpoint",
    "load_resume_state",
    "save_checkpoint",
    "validate_checkpoint_metadata",
]
