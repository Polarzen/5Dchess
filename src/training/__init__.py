"""Experimental Local AI Training v2 package.

This package is intentionally not imported by the normal game runtime.  Torch
and other training-only dependencies remain optional for players who only want
to run the engine, Web UI, Hotseat, P2P, Replay, or canonical baseline AIs.
"""

from src.training.config import (
    ACTION_ENCODING_VERSION,
    CHECKPOINT_FORMAT_VERSION,
    DATASET_SCHEMA_VERSION,
    ENGINE_BASELINE_SHA,
    STATE_ENCODING_VERSION,
)

__all__ = [
    "ACTION_ENCODING_VERSION",
    "CHECKPOINT_FORMAT_VERSION",
    "DATASET_SCHEMA_VERSION",
    "ENGINE_BASELINE_SHA",
    "STATE_ENCODING_VERSION",
]
