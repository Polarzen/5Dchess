"""TEMPORARY required-board progress ordering experiment. Remove after telemetry."""
from __future__ import annotations

import json
import time
import warnings

import src.ai.action_planner as action_planner
from src.ai.action_planner import ActionPlanner, ActionSearchBudget
from src.engine import ActionRules, FiveDEngine
from tests.training import test_planner_complex_fixture as fixture


def _run_progress_variant(engine: FiveDEngine, seconds: float) -> dict:
    original_required = ActionRules.required_boards
    original_key = action_planner._move_sort_key
    original_can_submit = FiveDEngine.can_submit_action
    required_now = set()
    started = None
    first_candidate_ms = None

    def tracked_required(action, timelines):
        nonlocal required_now
        value = original_required(action, timelines)
        required_now = set(value)
        return value

    def progress_key(move):
        progress = int(move.source.board in required_now)
        if (
            move.is_cross_timeline
            and move.destination.board != move.source.board
            and move.destination.board in required_now
        ):
            progress += 1
        return (-progress, original_key(move))

    def timed_can_submit(self, *args, **kwargs):
        nonlocal first_candidate_ms
        result = original_can_submit(self, *args, **kwargs)
        if result and first_candidate_ms is None and started is not None:
            first_candidate_ms = (time.perf_counter() - started) * 1000.0
        return result

    ActionRules.required_boards = staticmethod(tracked_required)
    action_planner._move_sort_key = progress_key
    FiveDEngine.can_submit_action = timed_can_submit
    try:
        started = time.perf_counter()
        result = ActionPlanner(ActionSearchBudget(
            max_states=128,
            max_actions=24,
            max_move_depth=32,
            max_seconds=seconds,
        )).search(engine)
        wall_ms = (time.perf_counter() - started) * 1000.0
    finally:
        ActionRules.required_boards = staticmethod(original_required)
        action_planner._move_sort_key = original_key
        FiveDEngine.can_submit_action = original_can_submit

    return {
        "budget": seconds,
        "first_candidate_ms": first_candidate_ms,
        "candidate_count": len(result.candidates),
        "first_candidate_depth": len(result.candidates[0]) if result.candidates else None,
        "explored_states": result.explored_states,
        "termination": result.termination_reason,
        "wall_ms": wall_ms,
    }


def test_required_board_progress_ordering_temp():
    engine = fixture.build_deterministic_complex_engine()
    report = [_run_progress_variant(engine, seconds) for seconds in (0.5, 1.0, 2.0)]
    warnings.warn("PLANNER_PROGRESS_VARIANT_TEMP=" + json.dumps(report, sort_keys=True))
    assert any(row["candidate_count"] for row in report)
