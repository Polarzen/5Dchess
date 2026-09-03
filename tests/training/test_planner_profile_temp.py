"""TEMPORARY complex ordering A/B diagnostic. Remove after telemetry."""
from __future__ import annotations

from copy import deepcopy
import json
import time
import warnings

import src.ai.action_planner as action_planner
from src.ai.action_planner import ActionPlanner, ActionSearchBudget
from src.engine import ActionRules, FiveDEngine
from src.utils.constants import PieceType
from tests.training import test_planner_complex_fixture as fixture


def _king_capture_key(move, required):
    base = action_planner._move_sort_key(move)
    if len(required) < 3:
        return base
    return (
        base[0],
        move.piece.piece_type is not PieceType.KING,
        move.captured is None,
        -action_planner._required_board_progress(move, required),
        *base[1:],
    )


def _measure(engine: FiveDEngine, seconds: float) -> dict:
    started = time.perf_counter()
    first_candidate_ms = None
    original_can_submit = FiveDEngine.can_submit_action

    def timed_can_submit(self, *args, **kwargs):
        nonlocal first_candidate_ms
        result = original_can_submit(self, *args, **kwargs)
        if result and first_candidate_ms is None:
            first_candidate_ms = (time.perf_counter() - started) * 1000.0
        return result

    FiveDEngine.can_submit_action = timed_can_submit
    try:
        result = ActionPlanner(ActionSearchBudget(
            max_states=256,
            max_actions=24,
            max_move_depth=64,
            max_seconds=seconds,
        )).search(engine)
    finally:
        FiveDEngine.can_submit_action = original_can_submit
    return {
        "budget": seconds,
        "first_candidate_ms": first_candidate_ms,
        "candidates": len(result.candidates),
        "first_depth": len(result.candidates[0]) if result.candidates else None,
        "explored": result.explored_states,
        "termination": result.termination_reason,
        "wall_ms": (time.perf_counter() - started) * 1000.0,
    }


def test_complex_king_first_dfs_temp():
    original = action_planner._required_move_sort_key
    action_planner._required_move_sort_key = _king_capture_key
    try:
        prefix = fixture.build_deterministic_complex_engine()
        final_state = deepcopy(prefix)
        fixture._apply_recorded_action(final_state, fixture.FINAL_ACTION, 34)
        assert len(ActionRules.required_boards(
            prefix._ensure_current_action(), prefix.timeline_manager.timelines
        )) == 16
        assert len(ActionRules.required_boards(
            final_state._ensure_current_action(), final_state.timeline_manager.timelines
        )) == 32
        report = {
            "required16": [_measure(prefix, seconds) for seconds in (0.5, 1.0, 2.0, 5.0)],
            "required32": [_measure(final_state, seconds) for seconds in (0.5, 1.0, 2.0, 5.0)],
        }
    finally:
        action_planner._required_move_sort_key = original
    warnings.warn("PLANNER_KING_FIRST_DFS_TEMP=" + json.dumps(report, sort_keys=True))
    assert any(row["candidates"] for row in report["required16"])
