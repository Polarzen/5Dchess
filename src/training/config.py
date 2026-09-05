"""Configuration and on-disk protocol versions for Local AI Training v2."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from typing import Any

ENGINE_BASELINE_SHA = "e3455901435e5c4dda66e5e141a9915fdfea0dee"
STATE_ENCODING_VERSION = 1
ACTION_ENCODING_VERSION = 1
DATASET_SCHEMA_VERSION = 1
CHECKPOINT_FORMAT_VERSION = 1

# Shared planner defaults and the explicit Arena wall-time contract.  Keep
# these values in the training configuration module so local and cloud entry
# points cannot drift apart.
DEFAULT_PLANNER_CANDIDATE_LIMIT = 24
DEFAULT_PLANNER_SECONDS = 0.5
DEFAULT_ARENA_PLANNER_SECONDS = DEFAULT_PLANNER_SECONDS
MIN_ARENA_PLANNER_SECONDS = 0.1
MAX_ARENA_PLANNER_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class EncodingConfig:
    """Bounded deterministic state/action representation sizes."""

    max_relevant_boards: int = 16
    max_moves_per_action: int = 32
    board_channels: int = 12
    board_meta_dim: int = 12
    global_dim: int = 16
    action_move_feature_dim: int = 40
    action_global_dim: int = 4

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Small policy/value network configuration."""

    preset: str = "small"
    conv_channels: int = 32
    board_embedding_dim: int = 64
    board_meta_hidden_dim: int = 32
    state_hidden_dim: int = 128
    move_hidden_dim: int = 64
    action_hidden_dim: int = 96
    joint_hidden_dim: int = 128
    dropout: float = 0.05

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlannerConfig:
    max_states: int = 256
    max_actions: int = DEFAULT_PLANNER_CANDIDATE_LIMIT
    max_move_depth: int = 32
    max_seconds: float = DEFAULT_PLANNER_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SelfPlayConfig:
    games: int = 100
    teacher: str = "mixed"
    seed: int = 42
    max_actions: int = 200
    shard_size: int = 256
    planner: PlannerConfig = PlannerConfig()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


@dataclass(frozen=True, slots=True)
class TrainConfig:
    epochs: int = 20
    batch_size: int = 64
    lr: float = 3e-4
    weight_decay: float = 1e-4
    value_weight: float = 0.5
    validation_fraction: float = 0.05
    seed: int = 42
    num_workers: int = 0
    grad_clip: float = 1.0
    mixed_precision: bool = True
    save_every: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PRESETS: dict[str, ModelConfig] = {
    "tiny": ModelConfig(
        preset="tiny",
        conv_channels=12,
        board_embedding_dim=24,
        board_meta_hidden_dim=16,
        state_hidden_dim=48,
        move_hidden_dim=24,
        action_hidden_dim=40,
        joint_hidden_dim=48,
        dropout=0.0,
    ),
    "small": ModelConfig(),
    "medium": ModelConfig(
        preset="medium",
        conv_channels=48,
        board_embedding_dim=96,
        board_meta_hidden_dim=48,
        state_hidden_dim=192,
        move_hidden_dim=96,
        action_hidden_dim=144,
        joint_hidden_dim=192,
        dropout=0.08,
    ),
}


def model_preset(name: str) -> ModelConfig:
    try:
        return _PRESETS[name.lower()]
    except KeyError as exc:
        raise ValueError(f"unknown model preset {name!r}; choose tiny/small/medium") from exc


def validate_arena_planner_seconds(value: Any) -> float:
    """Normalize and validate an explicit per-action planner wall budget."""
    if value is None or isinstance(value, bool):
        raise ValueError(
            "arena planner seconds must be a finite number in the range "
            f"{MIN_ARENA_PLANNER_SECONDS:g}..{MAX_ARENA_PLANNER_SECONDS:g}"
        )
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "arena planner seconds must be a finite number in the range "
            f"{MIN_ARENA_PLANNER_SECONDS:g}..{MAX_ARENA_PLANNER_SECONDS:g}"
        ) from exc
    if (
        seconds != seconds
        or seconds in {float("inf"), float("-inf")}
        or not MIN_ARENA_PLANNER_SECONDS <= seconds <= MAX_ARENA_PLANNER_SECONDS
    ):
        raise ValueError(
            "arena planner seconds must be a finite number in the range "
            f"{MIN_ARENA_PLANNER_SECONDS:g}..{MAX_ARENA_PLANNER_SECONDS:g}"
        )
    return seconds


def parse_arena_planner_seconds(value: Any) -> float:
    """Argparse adapter preserving the validator's clear error message."""
    try:
        return validate_arena_planner_seconds(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


DEFAULT_ENCODING = EncodingConfig()


__all__ = [
    "ACTION_ENCODING_VERSION",
    "CHECKPOINT_FORMAT_VERSION",
    "DATASET_SCHEMA_VERSION",
    "DEFAULT_ENCODING",
    "DEFAULT_ARENA_PLANNER_SECONDS",
    "DEFAULT_PLANNER_CANDIDATE_LIMIT",
    "DEFAULT_PLANNER_SECONDS",
    "ENGINE_BASELINE_SHA",
    "EncodingConfig",
    "MAX_ARENA_PLANNER_SECONDS",
    "MIN_ARENA_PLANNER_SECONDS",
    "ModelConfig",
    "PlannerConfig",
    "STATE_ENCODING_VERSION",
    "SelfPlayConfig",
    "TrainConfig",
    "model_preset",
    "parse_arena_planner_seconds",
    "validate_arena_planner_seconds",
]
