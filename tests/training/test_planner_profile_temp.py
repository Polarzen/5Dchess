"""TEMPORARY planner profiler. Remove after telemetry is collected."""
from __future__ import annotations

import builtins
from copy import deepcopy
import json
import statistics
import time
import warnings

import src.ai.action_planner as action_planner
from src.ai.action_planner import ActionPlanner, ActionSearchBudget
from src.engine import ActionRules, FiveDEngine
from src.engine.royal_rules import RoyalRules
from src.engine.timeline_rules import TimelineRules
from tests.training import test_planner_complex_fixture as fixture


def _summary(samples):
    if not samples:
        return {"calls": 0, "total_ms": 0.0, "median_ms": 0.0, "max_ms": 0.0}
    return {
        "calls": len(samples),
        "total_ms": sum(samples),
        "median_ms": statistics.median(samples),
        "max_ms": max(samples),
    }


def _profile(engine: FiveDEngine, *, seconds: float):
    samples = {
        "deepcopy": [],
        "get_legal_moves": [],
        "execute_action_move": [],
        "required_boards": [],
        "movable_boards": [],
        "can_submit_action": [],
        "timeline_present": [],
        "royal_is_action_safe": [],
        "sorting": [],
    }
    first_candidate_ms = None
    search_started = None

    original_deepcopy = action_planner.deepcopy
    original_sorted_present = hasattr(action_planner, "sorted")
    original_sorted = getattr(action_planner, "sorted", None)
    original_get_legal_moves = FiveDEngine.get_legal_moves
    original_execute = FiveDEngine.execute_action_move
    original_can_submit = FiveDEngine.can_submit_action
    original_required = ActionRules.required_boards
    original_movable = ActionRules.movable_boards
    original_present = TimelineRules.present
    original_royal_safe = RoyalRules.is_action_safe

    def timed(samples_key, fn, *args, **kwargs):
        started = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            samples[samples_key].append((time.perf_counter() - started) * 1000.0)

    def timed_deepcopy(value, memo=None, _nil=[]):
        started = time.perf_counter()
        try:
            if memo is None:
                return original_deepcopy(value)
            return original_deepcopy(value, memo)
        finally:
            samples["deepcopy"].append((time.perf_counter() - started) * 1000.0)

    def timed_sorted(iterable, *args, **kwargs):
        return timed("sorting", builtins.sorted, iterable, *args, **kwargs)

    def timed_get_legal_moves(self, *args, **kwargs):
        return timed("get_legal_moves", original_get_legal_moves, self, *args, **kwargs)

    def timed_execute(self, *args, **kwargs):
        return timed("execute_action_move", original_execute, self, *args, **kwargs)

    def timed_required(action, timelines):
        return timed("required_boards", original_required, action, timelines)

    def timed_movable(action, timelines):
        return timed("movable_boards", original_movable, action, timelines)

    def timed_present(cls, timelines):
        return timed("timeline_present", original_present, timelines)

    def timed_royal_safe(self, *args, **kwargs):
        return timed("royal_is_action_safe", original_royal_safe, self, *args, **kwargs)

    def timed_can_submit(self, *args, **kwargs):
        nonlocal first_candidate_ms
        started = time.perf_counter()
        try:
            result = original_can_submit(self, *args, **kwargs)
        finally:
            samples["can_submit_action"].append((time.perf_counter() - started) * 1000.0)
        if result and first_candidate_ms is None and search_started is not None:
            first_candidate_ms = (time.perf_counter() - search_started) * 1000.0
        return result

    action_planner.deepcopy = timed_deepcopy
    action_planner.sorted = timed_sorted
    FiveDEngine.get_legal_moves = timed_get_legal_moves
    FiveDEngine.execute_action_move = timed_execute
    FiveDEngine.can_submit_action = timed_can_submit
    ActionRules.required_boards = staticmethod(timed_required)
    ActionRules.movable_boards = staticmethod(timed_movable)
    TimelineRules.present = classmethod(timed_present)
    RoyalRules.is_action_safe = timed_royal_safe

    try:
        search_started = time.perf_counter()
        result = ActionPlanner(ActionSearchBudget(
            max_states=128,
            max_actions=1,
            max_move_depth=64,
            max_seconds=seconds,
        )).search(engine)
        wall_ms = (time.perf_counter() - search_started) * 1000.0
    finally:
        action_planner.deepcopy = original_deepcopy
        if original_sorted_present:
            action_planner.sorted = original_sorted
        else:
            delattr(action_planner, "sorted")
        FiveDEngine.get_legal_moves = original_get_legal_moves
        FiveDEngine.execute_action_move = original_execute
        FiveDEngine.can_submit_action = original_can_submit
        ActionRules.required_boards = staticmethod(original_required)
        ActionRules.movable_boards = staticmethod(original_movable)
        TimelineRules.present = classmethod(original_present.__func__) if hasattr(original_present, "__func__") else original_present
        RoyalRules.is_action_safe = original_royal_safe

    report = {name: _summary(values) for name, values in samples.items()}
    report.update({
        "wall_ms": wall_ms,
        "first_candidate_ms": first_candidate_ms,
        "candidate_count": len(result.candidates),
        "candidate_move_depth": len(result.candidates[0]) if result.candidates else None,
        "explored_states": result.explored_states,
        "termination": result.termination_reason,
        "nominal_budget": seconds,
    })
    return report


def test_profile_current_deterministic_prefix_temp():
    engine = fixture.build_deterministic_complex_engine()
    report = _profile(engine, seconds=2.0)
    warnings.warn("PLANNER_PROFILE_TEMP=" + json.dumps(report, sort_keys=True))
    assert report["candidate_count"] >= 1


def test_baseline_budget_matrix_temp():
    engine = fixture.build_deterministic_complex_engine()
    current_key = action_planner._move_sort_key
    matrix = {"legacy": [], "current": []}
    for seconds in (0.5, 1.0, 2.0, 5.0):
        matrix["legacy"].append(fixture._benchmark(engine, fixture._legacy_move_sort_key, seconds))
        matrix["current"].append(fixture._benchmark(engine, current_key, seconds))
    warnings.warn("PLANNER_BASELINE_MATRIX_TEMP=" + json.dumps(matrix, sort_keys=True))
    assert any(row["candidate_count"] for row in matrix["current"])
