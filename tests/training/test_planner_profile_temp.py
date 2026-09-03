"""TEMPORARY 32-board first-witness diagnostic. Remove after telemetry."""
from __future__ import annotations

from copy import deepcopy
import json
import time
import warnings

import src.ai.action_planner as action_planner
from src.ai.action_planner import MoveSpec
from src.engine import ActionRules, FiveDEngine
from src.engine.royal_rules import RoyalRules
from tests.training import test_planner_complex_fixture as fixture


def _coord(square):
    return [
        square.board.timeline,
        square.board.turn,
        square.board.side.value,
        square.x,
        square.y,
    ]


def _progress_key(move, required):
    return action_planner._required_move_sort_key(move, required)


def _base_key(move, required):
    del required
    return action_planner._move_sort_key(move)


def _spatial_key(move, required):
    del required
    base = action_planner._move_sort_key(move)
    return (base[0], not move.is_spatial, *base[1:])


def _single_clone_terminal(engine: FiveDEngine, move_key) -> dict:
    started = time.perf_counter()
    state = deepcopy(engine)
    state.timeline_manager.refresh_activity()
    state._ensure_current_action()
    path: list[MoveSpec] = []

    while True:
        action = state._ensure_current_action()
        required = set(ActionRules.required_boards(
            action, state.timeline_manager.timelines
        ))
        if not required:
            threats = RoyalRules(state.timeline_manager.timelines).direct_threats_against(
                action.color
            )
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
                "path": [
                    {"source": _coord(spec.source), "destination": _coord(spec.destination)}
                    for spec in path
                ],
            }

        movable = ActionRules.movable_boards(
            action, state.timeline_manager.timelines
        )
        ordered_boards = tuple(sorted(
            movable,
            key=lambda board: (
                board not in required,
                board.timeline,
                board.turn,
                board.side.value,
            ),
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
        assert state.execute_action_move(chosen)
        path.append(MoveSpec.from_move(chosen))
        assert len(path) <= 64


def test_32_board_first_witness_threats_temp():
    state = fixture.build_deterministic_complex_engine()
    fixture._apply_recorded_action(state, fixture.FINAL_ACTION, 34)
    required = ActionRules.required_boards(
        state._ensure_current_action(), state.timeline_manager.timelines
    )
    assert len(required) == 32
    report = {
        "progress": _single_clone_terminal(state, _progress_key),
        "base_nonbranching": _single_clone_terminal(state, _base_key),
        "spatial_first": _single_clone_terminal(state, _spatial_key),
    }
    warnings.warn("PLANNER_32_TERMINAL_THREATS_TEMP=" + json.dumps(report, sort_keys=True))
