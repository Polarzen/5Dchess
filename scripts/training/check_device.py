"""Print the Local AI Training v2 Torch/CUDA device report."""
from __future__ import annotations

import argparse

from src.training.utils import print_device_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()
    print_device_report(args.device)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
