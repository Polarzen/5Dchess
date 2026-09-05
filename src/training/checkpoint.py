"""Versioned safetensors checkpoints plus explicit trusted resume state."""
from __future__ import annotations

from dataclasses import asdict
import math
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


_REQUIRED_METADATA_KEYS = {
    "checkpoint_format_version",
    "state_encoding_version",
    "action_encoding_version",
    "dataset_schema_version",
    "engine_baseline_sha",
    "model_config",
    "encoding_config",
    "epoch",
    "global_step",
    "step",
    "seed",
    "best_validation_loss",
    "training_config",
}


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
        # ``step`` is the cloud-facing spelling.  Keep ``global_step`` for
        # compatibility with the original local training protocol and require
        # both values to agree when loading.
        "step": int(global_step),
        "seed": int(seed),
        "best_validation_loss": (
            None if best_validation_loss is None else float(best_validation_loss)
        ),
        "training_config": dict(training_config),
    }


def validate_checkpoint_metadata(metadata: dict[str, Any]) -> None:
    if not isinstance(metadata, dict):
        raise CheckpointFormatError("checkpoint metadata must be a JSON object")
    expected = {
        "checkpoint_format_version": CHECKPOINT_FORMAT_VERSION,
        "state_encoding_version": STATE_ENCODING_VERSION,
        "action_encoding_version": ACTION_ENCODING_VERSION,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "engine_baseline_sha": ENGINE_BASELINE_SHA,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise CheckpointFormatError(
                f"{key}={metadata.get(key)!r} is incompatible; expected {value!r}"
            )

    missing = sorted(_REQUIRED_METADATA_KEYS.difference(metadata))
    if missing:
        raise CheckpointFormatError(
            "checkpoint metadata is missing required keys: " + ", ".join(missing)
        )

    for key in ("epoch", "global_step", "step", "seed"):
        value = metadata[key]
        # bool is an int subclass but is not a meaningful checkpoint counter.
        if isinstance(value, bool) or not isinstance(value, int):
            raise CheckpointFormatError(f"metadata.{key} must be an integer")
        if key != "seed" and value < 0:
            raise CheckpointFormatError(f"metadata.{key} must be non-negative")
    if metadata["global_step"] != metadata["step"]:
        raise CheckpointFormatError("metadata.global_step and metadata.step disagree")

    best = metadata["best_validation_loss"]
    if best is not None:
        if isinstance(best, bool) or not isinstance(best, (int, float)):
            raise CheckpointFormatError("metadata.best_validation_loss must be a number or null")
        if not math.isfinite(float(best)):
            raise CheckpointFormatError("metadata.best_validation_loss must be finite")
    if not isinstance(metadata["model_config"], dict):
        raise CheckpointFormatError("metadata.model_config must be an object")
    if not isinstance(metadata["encoding_config"], dict):
        raise CheckpointFormatError("metadata.encoding_config must be an object")
    if not isinstance(metadata["training_config"], dict):
        raise CheckpointFormatError("metadata.training_config must be an object")

    model_keys = set(ModelConfig.__dataclass_fields__)
    encoding_keys = set(EncodingConfig.__dataclass_fields__)
    if set(metadata["model_config"]) != model_keys:
        raise CheckpointFormatError(
            "metadata.model_config fields do not match the supported model contract"
        )
    if set(metadata["encoding_config"]) != encoding_keys:
        raise CheckpointFormatError(
            "metadata.encoding_config fields do not match the supported encoding contract"
        )
    preset = metadata["model_config"].get("preset")
    if not isinstance(preset, str) or preset.lower() not in {"tiny", "small", "medium"}:
        raise CheckpointFormatError(f"unsupported model preset in metadata: {preset!r}")


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
    weights_tmp = directory / ".model.safetensors.tmp"
    cpu_state = {name: tensor.detach().cpu().contiguous() for name, tensor in model.state_dict().items()}
    # Write the complete file before replacing the published artifact.  A
    # runner killed during upload therefore leaves the previous checkpoint
    # readable instead of a partially written safetensors file.
    save_file(cpu_state, str(weights_tmp))
    weights_tmp.replace(weights_path)
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
            "step": int(global_step),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict() if scheduler is not None else None,
        }
        resume_path = directory / "resume_state.pt"
        resume_tmp = directory / ".resume_state.pt.tmp"
        torch.save(resume, resume_tmp)
        resume_tmp.replace(resume_path)
    else:
        # Do not leave a stale optimizer payload attached to a weights-only
        # checkpoint that was overwritten in place.
        stale_resume = directory / "resume_state.pt"
        if stale_resume.exists():
            stale_resume.unlink()
    return directory


def load_checkpoint(
    directory: str | Path,
    *,
    device="cpu",
) -> tuple[PolicyValueModel, dict[str, Any]]:
    directory = Path(directory).expanduser().resolve()
    metadata_path = directory / "metadata.json"
    weights_path = directory / "model.safetensors"
    if not metadata_path.is_file():
        raise CheckpointFormatError(f"checkpoint metadata not found: {metadata_path}")
    if not weights_path.is_file():
        raise CheckpointFormatError(f"checkpoint weights not found: {weights_path}")
    try:
        metadata = read_json(metadata_path)
    except (OSError, ValueError, TypeError) as exc:
        raise CheckpointFormatError(f"could not read checkpoint metadata: {metadata_path}") from exc
    validate_checkpoint_metadata(metadata)
    try:
        model_config = ModelConfig(**metadata["model_config"])
        encoding_config = EncodingConfig(**metadata["encoding_config"])
        model = PolicyValueModel(model_config, encoding_config)
        state = load_file(str(weights_path), device=str(device))
        model.load_state_dict(state, strict=True)
    except (TypeError, ValueError, KeyError, RuntimeError, OSError) as exc:
        raise CheckpointFormatError(
            f"checkpoint model/encoding payload is incompatible: {directory}"
        ) from exc
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
    metadata_path = directory / "metadata.json"
    path = directory / "resume_state.pt"
    if not metadata_path.is_file():
        raise CheckpointFormatError(f"checkpoint metadata not found: {metadata_path}")
    try:
        metadata = read_json(metadata_path)
    except (OSError, ValueError, TypeError) as exc:
        raise CheckpointFormatError(f"could not read checkpoint metadata: {metadata_path}") from exc
    validate_checkpoint_metadata(metadata)
    if not path.is_file():
        raise FileNotFoundError(f"resume state not found: {path}")
    try:
        state = torch.load(path, map_location=device, weights_only=False)
    except TypeError:
        state = torch.load(path, map_location=device)
    except (OSError, RuntimeError, ValueError, EOFError) as exc:
        raise CheckpointFormatError(f"could not read resume state: {path}") from exc
    if not isinstance(state, dict):
        raise CheckpointFormatError("resume state must be a mapping")
    required = {"epoch", "global_step", "step", "optimizer", "scheduler"}
    missing = sorted(required.difference(state))
    if missing:
        raise CheckpointFormatError(
            "resume state is missing required keys: " + ", ".join(missing)
        )
    for key in ("epoch", "global_step", "step"):
        if isinstance(state[key], bool) or not isinstance(state[key], int) or state[key] < 0:
            raise CheckpointFormatError(f"resume.{key} must be a non-negative integer")
    if int(state["epoch"]) != int(metadata["epoch"]):
        raise CheckpointFormatError("resume epoch disagrees with checkpoint metadata")
    if int(state["global_step"]) != int(metadata["global_step"]):
        raise CheckpointFormatError("resume global_step disagrees with checkpoint metadata")
    if int(state["step"]) != int(state["global_step"]):
        raise CheckpointFormatError("resume global_step and step disagree")
    try:
        optimizer.load_state_dict(state["optimizer"])
        if scheduler is not None and state.get("scheduler") is not None:
            scheduler.load_state_dict(state["scheduler"])
    except (KeyError, RuntimeError, ValueError, TypeError) as exc:
        raise CheckpointFormatError("resume optimizer/scheduler state is incompatible") from exc
    return int(state["epoch"]), int(state["global_step"])


def validate_resume_payload(directory: str | Path, *, device="cpu") -> dict[str, Any]:
    """Validate resume-file structure/counters without mutating an optimizer.

    This is used by cloud artifact validation before a training process has
    constructed its optimizer.  The file is still an explicitly trusted
    Torch payload, matching ``load_resume_state``'s local-resume contract.
    """
    directory = Path(directory).expanduser().resolve()
    metadata_path = directory / "metadata.json"
    path = directory / "resume_state.pt"
    if not metadata_path.is_file():
        raise CheckpointFormatError(f"checkpoint metadata not found: {metadata_path}")
    if not path.is_file():
        raise CheckpointFormatError(f"resume state not found: {path}")
    try:
        metadata = read_json(metadata_path)
    except (OSError, ValueError, TypeError) as exc:
        raise CheckpointFormatError(f"could not read checkpoint metadata: {metadata_path}") from exc
    validate_checkpoint_metadata(metadata)
    try:
        state = torch.load(path, map_location=device, weights_only=False)
    except TypeError:
        try:
            state = torch.load(path, map_location=device)
        except (OSError, RuntimeError, ValueError, EOFError) as exc:
            raise CheckpointFormatError(f"could not read resume state: {path}") from exc
    except (OSError, RuntimeError, ValueError, EOFError) as exc:
        raise CheckpointFormatError(f"could not read resume state: {path}") from exc
    if not isinstance(state, dict):
        raise CheckpointFormatError("resume state must be a mapping")
    required = {"epoch", "global_step", "step", "optimizer", "scheduler"}
    missing = sorted(required.difference(state))
    if missing:
        raise CheckpointFormatError(
            "resume state is missing required keys: " + ", ".join(missing)
        )
    for key in ("epoch", "global_step", "step"):
        if isinstance(state[key], bool) or not isinstance(state[key], int) or state[key] < 0:
            raise CheckpointFormatError(f"resume.{key} must be a non-negative integer")
    if int(state["epoch"]) != int(metadata["epoch"]):
        raise CheckpointFormatError("resume epoch disagrees with checkpoint metadata")
    if int(state["global_step"]) != int(metadata["global_step"]):
        raise CheckpointFormatError("resume global_step disagrees with checkpoint metadata")
    if int(state["step"]) != int(state["global_step"]):
        raise CheckpointFormatError("resume global_step and step disagree")
    return {"metadata": metadata, "state": state}


__all__ = [
    "CheckpointFormatError",
    "load_checkpoint",
    "load_resume_state",
    "save_checkpoint",
    "validate_resume_payload",
    "validate_checkpoint_metadata",
]
