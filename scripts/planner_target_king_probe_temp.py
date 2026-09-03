"""Temporary exact-state probe for two-required-board King/capture ordering."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.planner_target_order_probe_temp as probe
from src.ai.action_planner import _move_sort_key
from src.utils.constants import PieceType


def _progress(move, required) -> int:
    value = int(move.source.board in required)
    if (
        len(required) > 1
        and move.is_cross_timeline
        and not move.is_branching
        and move.destination.board != move.source.board
        and move.destination.board in required
    ):
        value += 1
    return value


def _two_board_completion_key(move, required):
    base = _move_sort_key(move)
    if len(required) != 2:
        return probe._required_move_sort_key(move, required)
    return (
        base[0],
        -_progress(move, required),
        move.piece.piece_type is not PieceType.KING,
        move.captured is None,
        *base[1:],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engine = probe.build_engine(args.trace)
    original = probe._required_move_sort_key
    probe._required_move_sort_key = _two_board_completion_key
    try:
        results = [
            probe.run_search(engine, "global-static", 1.0),
            probe.run_search(engine, "global-static", 5.0),
        ]
    finally:
        probe._required_move_sort_key = original
    report = {"variant": "global-required-king-capture", "searches": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
