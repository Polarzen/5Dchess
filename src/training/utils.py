"""Small reproducibility, device, and JSON helpers for training."""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path
from typing import Any

import numpy as np


def seed_everything(seed: int, *, deterministic: bool = True) -> None:
    """Seed Python, NumPy and Torch without making Torch a runtime dependency."""
    seed = int(seed)
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import torch
    except ImportError:
        return
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if deterministic:
        try:
            torch.use_deterministic_algorithms(True, warn_only=True)
        except (AttributeError, RuntimeError):
            pass


def resolve_device(requested: str = "auto"):
    """Return a torch.device for auto/cpu/cuda and fail clearly for bad CUDA."""
    import torch

    requested = requested.lower().strip()
    if requested not in {"auto", "cpu", "cuda"}:
        raise ValueError("device must be one of: auto, cpu, cuda")
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but torch.cuda.is_available() is False")
        return torch.device("cuda")
    if requested == "auto" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def device_report(requested: str = "auto") -> dict[str, Any]:
    import torch

    device = resolve_device(requested)
    report: dict[str, Any] = {
        "python": sys.version.split()[0],
        "torch": torch.__version__,
        "requested": requested,
        "device": str(device),
        "cuda_available": bool(torch.cuda.is_available()),
        "torch_cuda_version": torch.version.cuda,
        "gpu_name": None,
        "gpu_vram_bytes": None,
    }
    if torch.cuda.is_available():
        index = torch.cuda.current_device()
        report["gpu_name"] = torch.cuda.get_device_name(index)
        try:
            report["gpu_vram_bytes"] = int(torch.cuda.get_device_properties(index).total_memory)
        except Exception:
            pass
    return report


def print_device_report(requested: str = "auto") -> dict[str, Any]:
    report = device_report(requested)
    print("Training device report")
    for key, value in report.items():
        if key == "gpu_vram_bytes" and value:
            value = f"{value / (1024 ** 3):.2f} GiB"
        print(f"  {key}: {value}")
    return report


def write_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp.replace(path)


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ensure_output_directory(path: str | Path) -> Path:
    """Create a training output path without allowing the repository root itself."""
    path = Path(path).expanduser().resolve()
    cwd = Path.cwd().resolve()
    if path == cwd:
        raise ValueError("refusing to write training output directly into repository root")
    path.mkdir(parents=True, exist_ok=True)
    return path


__all__ = [
    "device_report",
    "ensure_output_directory",
    "print_device_report",
    "read_json",
    "resolve_device",
    "seed_everything",
    "write_json",
]
