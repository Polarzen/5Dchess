"""Temporary deterministic search-order probe for captured Arena failure state.

The input trace is downloaded from GitHub Actions run 33813126560. All probes
operate on deep copies and only change exploration order; canonical Move
generation/execution and submit legality remain untouched.
"""
from __future__ import annotations

from copy import deepcopy
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ai.action_planner import (
    _move_sort_key,
    _required_move_sort_key,
)
from src.engine import ActionRules, BoardCoord, FiveDEngine, Square5D
from src.engine.action_search import ActionSearch
from src.utils.constants import ChessColor, PieceType


def _square(raw) -> Square5D:
    timeline, turn, side, x, y = raw
    return Square5D(BoardCoord(timeline, turn, ChessColor(side)), x, y)


def build_engine(trace_path: Path) -> FiveDEngine:
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    engine = FiveDEngine()
    for action_index, action_specs in enumerate(trace):
        for spec in action_specs:
            source = _square(spec["source"])
            destination = _square(spec["destination"])
            promotion = PieceType(spec["promotion"]) if spec.get("promotion") else None
            position = engine._resolve_position(source.board)
            assert position is not None, (action_index, spec)
            matches = [
                move for move in engine.get_legal_moves(position)
                if move.source == source
                and move.destination == destination
                and move.promotion == promotion
            ]
            assert len(matches) == 1, (action_index, spec, len(matches))
            assert engine.execute_action_move(matches[0]), (action_index, spec)
        assert engine.can_submit_action(), action_index
        assert engine.submit_action(), action_index
    return engine


def _move_json(move, required) -> dict:
    return {
        "source_board": [move.source.board.timeline, move.source.board.turn, move.source.board.side.value],
        "destination_board": [move.destination.board.timeline, move.destination.board.turn, move.destination.board.side.value],
        "source_xy": [move.source.x, move.source.y],
        "destination_xy": [move.destination.x, move.destination.y],
        "piece": move.piece.piece_type.value,
        "capture": move.captured is not None,
        "branching": bool(move.is_branching),
        "cross_timeline": bool(move.is_cross_timeline),
        "source_required": move.source.board in required,
        "destination_required": move.destination.board in required,
    }


def root_inventory(engine: FiveDEngine) -> dict:
    action = engine._ensure_current_action()
    required = set(ActionRules.required_boards(action, engine.timeline_manager.timelines))
    movable = tuple(ActionRules.movable_boards(action, engine.timeline_manager.timelines))
    rows = []
    all_moves = []
    for board in sorted(movable, key=lambda b: (b not in required, b.timeline, b.turn, b.side.value)):
        position = engine._resolve_position(board)
        moves = list(engine.get_legal_moves(position)) if position is not None else []
        ordered = sorted(moves, key=lambda m: _required_move_sort_key(m, required))
        rows.append({
            "board": [board.timeline, board.turn, board.side.value],
            "required": board in required,
            "legal_moves": len(moves),
            "first_moves": [_move_json(m, required) for m in ordered[:8]],
        })
        all_moves.extend(moves)
    global_ordered = sorted(
        all_moves,
        key=lambda m: (
            m.source.board not in required,
            _required_move_sort_key(m, required),
        ),
    )
    return {
        "required": [[b.timeline, b.turn, b.side.value] for b in sorted(required, key=lambda b:(b.timeline,b.turn,b.side.value))],
        "movable_count": len(movable),
        "total_root_moves": len(all_moves),
        "boards": rows,
        "global_first_moves": [_move_json(m, required) for m in global_ordered[:24]],
    }


class OrderedWitnessSearch(ActionSearch):
    """ActionSearch variant changing ordering only for diagnostic A/B."""

    def __init__(self, *, mode: str, **kwargs):
        super().__init__(**kwargs)
        self.mode = mode

    def _dfs(self, state: FiveDEngine, depth: int):
        action = state._ensure_current_action()
        required = set(ActionRules.required_boards(action, state.timeline_manager.timelines))
        if not required and ActionRules.can_submit(action, state.timeline_manager.timelines):
            return tuple(action.moves)
        if self._budget_exhausted(depth):
            return None
        key = self._state_key(state)
        if key in self._failed_states:
            return None
        self._explored_states += 1
        movable = ActionRules.movable_boards(action, state.timeline_manager.timelines)
        if not movable:
            self._failed_states.add(key)
            return None

        board_key = lambda b: (b not in required, b.timeline, b.turn, b.side.value)
        boards = list(sorted(movable, key=board_key))
        if self.mode == "reverse-required":
            required_part = [b for b in boards if b in required]
            optional_part = [b for b in boards if b not in required]
            boards = list(reversed(required_part)) + optional_part

        prepared = []
        for board in boards:
            position = state._resolve_position(board)
            if position is None:
                continue
            moves = list(state.get_legal_moves(position))
            if self.mode in {"global-static", "global-child"}:
                for move in moves:
                    prepared.append((board, move, None))
            else:
                moves = sorted(moves, key=lambda m: _required_move_sort_key(m, required))
                for move in moves:
                    prepared.append((board, move, None))

        if self.mode == "global-static":
            prepared.sort(key=lambda item: (
                item[1].source.board not in required,
                _required_move_sort_key(item[1], required),
            ))
        elif self.mode == "global-child":
            scored = []
            for board, move, _ in prepared:
                if self._termination_reason is not None:
                    return None
                child = deepcopy(state)
                if not child.execute_action_move(move):
                    continue
                child_action = child._ensure_current_action()
                child_required = set(ActionRules.required_boards(child_action, child.timeline_manager.timelines))
                scored.append((
                    (
                        len(child_required),
                        bool(move.is_branching),
                        move.piece.piece_type is not PieceType.KING,
                        move.captured is None,
                        _move_sort_key(move),
                    ),
                    board,
                    move,
                    child,
                ))
            scored.sort(key=lambda item: item[0])
            prepared = [(board, move, child) for _, board, move, child in scored]

        for _, move, prepared_child in prepared:
            if self._termination_reason is not None:
                return None
            child = prepared_child if prepared_child is not None else deepcopy(state)
            if prepared_child is None and not child.execute_action_move(move):
                continue
            witness = self._dfs(child, depth + 1)
            if witness is not None:
                return witness

        if self._termination_reason is None:
            self._failed_states.add(key)
        return None


def run_search(engine: FiveDEngine, mode: str, seconds: float) -> dict:
    started = time.perf_counter()
    search = OrderedWitnessSearch(
        mode=mode,
        max_states=16384,
        max_depth=64,
        max_seconds=seconds,
    )
    result = search.find_legal_completion(engine)
    return {
        "mode": mode,
        "budget_seconds": seconds,
        "wall_ms": (time.perf_counter() - started) * 1000.0,
        "has_legal_action": result.has_legal_action,
        "explored_states": result.explored_states,
        "termination_reason": result.termination_reason,
        "witness_length": len(result.witness),
        "witness": [_move_json(move, set()) for move in result.witness],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engine = build_engine(args.trace)
    report = {
        "state": {
            "player": engine.current_turn_color.value,
            "move_counter": engine.move_counter,
            "timeline_count": len(engine.timeline_manager.timelines),
        },
        "root": root_inventory(engine),
        "searches": [],
    }
    for mode, seconds in (
        ("nested", 5.0),
        ("reverse-required", 5.0),
        ("global-static", 5.0),
        ("global-child", 5.0),
        ("global-static", 20.0),
        ("global-child", 20.0),
    ):
        result = run_search(engine, mode, seconds)
        report["searches"].append(result)
        print(json.dumps(result, sort_keys=True))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
