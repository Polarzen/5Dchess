"""Versioned, non-pickle, shard-based Local AI Training dataset."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from src.training.config import (
    ACTION_ENCODING_VERSION,
    DATASET_SCHEMA_VERSION,
    ENGINE_BASELINE_SHA,
    STATE_ENCODING_VERSION,
)
from src.training.encoding import EncodedCandidates, EncodedState
from src.training.utils import ensure_output_directory, read_json, write_json


class DatasetFormatError(ValueError):
    pass


@dataclass(slots=True)
class TrainingSample:
    state: EncodedState
    candidates: EncodedCandidates
    selected_index: int
    value_target: float
    value_mask: bool
    player_color: int
    game_id: int
    action_index: int
    termination_reason: str

    def validate(self) -> None:
        count = self.candidates.candidate_count
        if count <= 0:
            raise DatasetFormatError("sample has no legal candidates")
        if not 0 <= int(self.selected_index) < count:
            raise DatasetFormatError(
                f"selected_index {self.selected_index} outside candidate count {count}"
            )
        if self.player_color not in (-1, 1):
            raise DatasetFormatError("player_color must be +1 (white) or -1 (black)")


class DatasetWriter:
    """Append complete numeric shards; an interrupted later shard cannot corrupt prior ones."""

    def __init__(
        self,
        output: str | Path,
        *,
        generator_config: dict[str, Any],
        seed: int,
        shard_size: int = 256,
        resume: bool = False,
    ) -> None:
        self.output = ensure_output_directory(output)
        self.metadata_path = self.output / "metadata.json"
        self.shard_size = max(1, int(shard_size))
        self._pending: list[TrainingSample] = []
        if self.metadata_path.exists():
            if not resume:
                raise FileExistsError(
                    f"dataset already exists at {self.output}; choose a new output or --resume"
                )
            self.metadata = read_json(self.metadata_path)
            validate_metadata(self.metadata)
        else:
            self.metadata = {
                "dataset_schema_version": DATASET_SCHEMA_VERSION,
                "state_encoding_version": STATE_ENCODING_VERSION,
                "action_encoding_version": ACTION_ENCODING_VERSION,
                "engine_baseline_sha": ENGINE_BASELINE_SHA,
                "generator_config": generator_config,
                "seed": int(seed),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "sample_count": 0,
                "game_count": 0,
                "shards": [],
            }
            write_json(self.metadata_path, self.metadata)

    @property
    def sample_count(self) -> int:
        return int(self.metadata["sample_count"]) + len(self._pending)

    @property
    def game_count(self) -> int:
        return int(self.metadata["game_count"])

    def add(self, sample: TrainingSample) -> None:
        sample.validate()
        self._pending.append(sample)
        if len(self._pending) >= self.shard_size:
            self.flush()

    def finish_game(self) -> None:
        self.metadata["game_count"] = int(self.metadata["game_count"]) + 1
        write_json(self.metadata_path, self.metadata)

    def flush(self) -> None:
        if not self._pending:
            return
        samples = self._pending
        max_candidates = max(sample.candidates.candidate_count for sample in samples)
        first = samples[0]
        state_shape = first.state.boards.shape
        board_meta_shape = first.state.board_meta.shape
        board_mask_shape = first.state.board_mask.shape
        global_shape = first.state.global_features.shape
        action_move_shape = first.candidates.moves.shape[1:]
        action_global_dim = first.candidates.action_global.shape[-1]

        count = len(samples)
        arrays: dict[str, np.ndarray] = {
            "state_boards": np.zeros((count, *state_shape), dtype=np.float32),
            "board_meta": np.zeros((count, *board_meta_shape), dtype=np.float32),
            "board_mask": np.zeros((count, *board_mask_shape), dtype=np.bool_),
            "state_global": np.zeros((count, *global_shape), dtype=np.float32),
            "action_moves": np.zeros(
                (count, max_candidates, *action_move_shape), dtype=np.float32
            ),
            "action_move_mask": np.zeros(
                (count, max_candidates, action_move_shape[0]), dtype=np.bool_
            ),
            "action_global": np.zeros(
                (count, max_candidates, action_global_dim), dtype=np.float32
            ),
            "candidate_mask": np.zeros((count, max_candidates), dtype=np.bool_),
            "selected_index": np.zeros((count,), dtype=np.int64),
            "value_target": np.zeros((count,), dtype=np.float32),
            "value_mask": np.zeros((count,), dtype=np.bool_),
            "player_color": np.zeros((count,), dtype=np.int8),
            "game_id": np.zeros((count,), dtype=np.int64),
            "action_index": np.zeros((count,), dtype=np.int64),
            "termination_reason": np.empty((count,), dtype="<U32"),
        }
        for row, sample in enumerate(samples):
            candidate_count = sample.candidates.candidate_count
            arrays["state_boards"][row] = sample.state.boards
            arrays["board_meta"][row] = sample.state.board_meta
            arrays["board_mask"][row] = sample.state.board_mask
            arrays["state_global"][row] = sample.state.global_features
            arrays["action_moves"][row, :candidate_count] = sample.candidates.moves[:candidate_count]
            arrays["action_move_mask"][row, :candidate_count] = sample.candidates.move_mask[:candidate_count]
            arrays["action_global"][row, :candidate_count] = sample.candidates.action_global[:candidate_count]
            arrays["candidate_mask"][row, :candidate_count] = True
            arrays["selected_index"][row] = int(sample.selected_index)
            arrays["value_target"][row] = float(sample.value_target)
            arrays["value_mask"][row] = bool(sample.value_mask)
            arrays["player_color"][row] = int(sample.player_color)
            arrays["game_id"][row] = int(sample.game_id)
            arrays["action_index"][row] = int(sample.action_index)
            arrays["termination_reason"][row] = str(sample.termination_reason)[:32]

        shard_index = len(self.metadata["shards"])
        filename = f"shard_{shard_index:06d}.npz"
        final_path = self.output / filename
        temp_path = self.output / f".{filename}.tmp.npz"
        np.savez(temp_path, **arrays)
        temp_path.replace(final_path)
        self.metadata["shards"].append({"file": filename, "samples": count})
        self.metadata["sample_count"] = int(self.metadata["sample_count"]) + count
        write_json(self.metadata_path, self.metadata)
        self._pending = []

    def close(self) -> None:
        self.flush()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Completed samples are still useful after Ctrl+C or a bounded generator stop.
        self.flush()
        return False


def validate_metadata(metadata: dict[str, Any]) -> None:
    expected = {
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "state_encoding_version": STATE_ENCODING_VERSION,
        "action_encoding_version": ACTION_ENCODING_VERSION,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise DatasetFormatError(
                f"{key}={metadata.get(key)!r} is incompatible; expected {value!r}"
            )
    if not isinstance(metadata.get("shards"), list):
        raise DatasetFormatError("metadata.shards must be a list")


class ShardedDataset:
    """Map-style dataset that keeps at most one NPZ shard open in memory."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.metadata = read_json(self.root / "metadata.json")
        validate_metadata(self.metadata)
        self._shards = list(self.metadata["shards"])
        self._offsets: list[int] = [0]
        for shard in self._shards:
            self._offsets.append(self._offsets[-1] + int(shard["samples"]))
        self._cached_index: int | None = None
        self._cached: dict[str, np.ndarray] | None = None

    def __len__(self) -> int:
        return self._offsets[-1]

    def _load_shard(self, shard_index: int) -> dict[str, np.ndarray]:
        if self._cached_index == shard_index and self._cached is not None:
            return self._cached
        path = self.root / self._shards[shard_index]["file"]
        with np.load(path, allow_pickle=False) as data:
            loaded = {name: data[name] for name in data.files}
        self._cached_index = shard_index
        self._cached = loaded
        return loaded

    def __getitem__(self, index: int) -> dict[str, np.ndarray | int | float | bool | str]:
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        shard_index = bisect_right(self._offsets, index) - 1
        local_index = index - self._offsets[shard_index]
        shard = self._load_shard(shard_index)
        candidate_count = int(shard["candidate_mask"][local_index].sum())
        return {
            "state_boards": shard["state_boards"][local_index],
            "board_meta": shard["board_meta"][local_index],
            "board_mask": shard["board_mask"][local_index],
            "state_global": shard["state_global"][local_index],
            "action_moves": shard["action_moves"][local_index, :candidate_count],
            "action_move_mask": shard["action_move_mask"][local_index, :candidate_count],
            "action_global": shard["action_global"][local_index, :candidate_count],
            "candidate_mask": shard["candidate_mask"][local_index, :candidate_count],
            "selected_index": int(shard["selected_index"][local_index]),
            "value_target": float(shard["value_target"][local_index]),
            "value_mask": bool(shard["value_mask"][local_index]),
            "player_color": int(shard["player_color"][local_index]),
            "game_id": int(shard["game_id"][local_index]),
            "action_index": int(shard["action_index"][local_index]),
            "termination_reason": str(shard["termination_reason"][local_index]),
        }


def collate_training_batch(samples: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Pad only the dynamic candidate dimension and return Torch tensors."""
    import torch

    samples = list(samples)
    if not samples:
        raise ValueError("cannot collate an empty batch")
    batch = len(samples)
    max_candidates = max(sample["action_moves"].shape[0] for sample in samples)
    move_shape = samples[0]["action_moves"].shape[1:]
    action_global_dim = samples[0]["action_global"].shape[-1]

    def stack(name: str, dtype=None):
        tensor = torch.as_tensor(np.stack([sample[name] for sample in samples]))
        return tensor.to(dtype=dtype) if dtype is not None else tensor

    action_moves = torch.zeros((batch, max_candidates, *move_shape), dtype=torch.float32)
    action_move_mask = torch.zeros(
        (batch, max_candidates, move_shape[0]), dtype=torch.bool
    )
    action_global = torch.zeros(
        (batch, max_candidates, action_global_dim), dtype=torch.float32
    )
    candidate_mask = torch.zeros((batch, max_candidates), dtype=torch.bool)
    for row, sample in enumerate(samples):
        count = sample["action_moves"].shape[0]
        action_moves[row, :count] = torch.as_tensor(sample["action_moves"], dtype=torch.float32)
        action_move_mask[row, :count] = torch.as_tensor(sample["action_move_mask"], dtype=torch.bool)
        action_global[row, :count] = torch.as_tensor(sample["action_global"], dtype=torch.float32)
        candidate_mask[row, :count] = True

    return {
        "state_boards": stack("state_boards", torch.float32),
        "board_meta": stack("board_meta", torch.float32),
        "board_mask": stack("board_mask", torch.bool),
        "state_global": stack("state_global", torch.float32),
        "action_moves": action_moves,
        "action_move_mask": action_move_mask,
        "action_global": action_global,
        "candidate_mask": candidate_mask,
        "selected_index": torch.tensor([sample["selected_index"] for sample in samples], dtype=torch.long),
        "value_target": torch.tensor([sample["value_target"] for sample in samples], dtype=torch.float32),
        "value_mask": torch.tensor([sample["value_mask"] for sample in samples], dtype=torch.bool),
    }


def split_indices(
    sample_count: int,
    validation_fraction: float,
    seed: int,
) -> tuple[list[int], list[int]]:
    if sample_count <= 0:
        raise ValueError("dataset has no samples")
    if not 0.0 <= validation_fraction < 1.0:
        raise ValueError("validation_fraction must be in [0, 1)")
    rng = np.random.default_rng(int(seed))
    indices = np.arange(sample_count)
    rng.shuffle(indices)
    if sample_count == 1 or validation_fraction == 0.0:
        return indices.tolist(), []
    validation_count = max(1, int(round(sample_count * validation_fraction)))
    validation_count = min(validation_count, sample_count - 1)
    validation = indices[:validation_count].tolist()
    train = indices[validation_count:].tolist()
    return train, validation


__all__ = [
    "DatasetFormatError",
    "DatasetWriter",
    "ShardedDataset",
    "TrainingSample",
    "collate_training_batch",
    "split_indices",
    "validate_metadata",
]
