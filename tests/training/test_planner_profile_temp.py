"""TEMPORARY 32-board first-witness ordering diagnostic. Remove after telemetry."""
from __future__ import annotations

from copy import deepcopy
import json
import time
import warnings

import src.ai.action_planner as action_planner
from src.ai.action_planner import MoveSpec
from src.engine import ActionRules, FiveDEngine
from src.engine.royal_rules import RoyalRules
from src.utils.constants import PieceType
from tests.training import test_planner_complex_fixture as fixture


def _coord(square):
    return [square.board.timeline, square.board.turn, square.board.side.value, square.x, square.y]


def _base(move):
    return action_planner._move_sort_key(move)


def _progress_key(move, required):
    return action_planner._required_move_sort_key(move, required)


def _capture_first_key(move, required):
    base = _base(move)
    return (base[0], move.captured is None, -action_planner._required_board_progress(move, required), *base[1:])


def _progress_capture_key(move, required):
    base = _base(move)
    return (base[0], -action_planner._required_board_progress(move, required), move.captured is None, *base[1:])


def _king_capture_key(move, required):
    base = _base(move)
    return (
        base[0],
        move.piece.piece_type is not PieceType.KING,
        move.captured is None,
        -action_planner._required_board_progress(move, required),
        *base[1:],
    )


def _capture_king_key(move, required):
    base = _base(move)
    return (
        base[0],
        move.captured is None,
        move.piece.piece_type is not PieceType.KING,
        -action_planner._required_board_progress(move, required),
        *base[1:],
    )


def _single_clone_terminal(engine: FiveDEngine, move_key) -> dict:
    started = time.perf_counter()
    state = deepcopy(engine)
    state.timeline_manager.refresh_activity()
    state._ensure_current_action()
    path = []

    while True:
        action = state._ensure_current_action()
        required = set(ActionRules.required_boards(action, state.timeline_manager.timelines))
        if not required:
            threats = RoyalRules(state.timeline_manager.timelines).direct_threats_against(action.color)
            safe = state.can_submit_action()
            return {
                "safe": safe,
                "depth": len(path),
                "wall_ms": (time.perf_counter() - started) * 1000.0,
                "threat_count": len(threats),
                "threats": [
                    {
                        "piece": threat.piece.piece_type.value,
                        "attacker": _coord(threat.attacker),
                        "king": _coord(threat.king),
                    }
                    for threat in threats[:12]
                ],
                "path": path,
            }

        movable = ActionRules.movable_boards(action, state.timeline_manager.timelines)
        ordered_boards = tuple(sorted(
            movable,
            key=lambda board: (board not in required, board.timeline, board.turn, board.side.value),
        ))
        chosen = None
        for board in ordered_boards:
            position = state._resolve_position(board)
            if position is None:
                continue
            legal_moves = sorted(
                state.get_legal_moves(position),
                key=lambda move: move_key(move, required),
            )
            if legal_moves:
                chosen = legal_moves[0]
                break
        assert chosen is not None
        path.append({
            "piece": chosen.piece.piece_type.value,
            "captured": chosen.captured.piece_type.value if chosen.captured else None,
            "source": _coord(chosen.source),
            "destination": _coord(chosen.destination),
        })
        assert state.execute_action_move(chosen)
        assert len(path) <= 64


def test_32_board_capture_ordering_temp():
    state = fixture.build_deterministic_complex_engine()
    fixture._apply_recorded_action(state, fixture.FINAL_ACTION, 34)
    required = ActionRules.required_boards(state._ensure_current_action(), state.timeline_manager.timelines)
    assert len(required) == 32
    variants = {
        "progress": _progress_key,
        "capture_first": _capture_first_key,
        "progress_capture": _progress_capture_key,
        "king_capture": _king_capture_key,
        "capture_king": _capture_king_key,
    }
    report = {name: _single_clone_terminal(state, key) for name, key in variants.items()}
    warnings.warn("PLANNER_32_CAPTURE_ORDER_TEMP=" + json.dumps(report, sort_keys=True))
