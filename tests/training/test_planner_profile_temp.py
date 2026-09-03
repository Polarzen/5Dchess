"""TEMPORARY planner profiler. Remove after telemetry is collected."""
from __future__ import annotations

import builtins
from copy import deepcopy
import json
import statistics
import time
import warnings

import src.ai.action_planner as action_planner
from src.ai.action_planner import ActionPlanner, ActionSearchBudget, MoveSpec
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


def _measure(engine: FiveDEngine, seconds: float) -> dict:
    original_can_submit = FiveDEngine.can_submit_action
    started = time.perf_counter()
    first_candidate_ms = None

    def timed_can_submit(self, *args, **kwargs):
        nonlocal first_candidate_ms
        result = original_can_submit(self, *args, **kwargs)
        if result and first_candidate_ms is None:
            first_candidate_ms = (time.perf_counter() - started) * 1000.0
        return result

    FiveDEngine.can_submit_action = timed_can_submit
    try:
        result = ActionPlanner(ActionSearchBudget(
            max_states=128,
            max_actions=24,
            max_move_depth=64,
            max_seconds=seconds,
        )).search(engine)
        wall_ms = (time.perf_counter() - started) * 1000.0
    finally:
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


def _progress_key(move, required):
    return action_planner._required_move_sort_key(move, required)


def _base_key(move, required):
    del required
    return action_planner._move_sort_key(move)


def _spatial_key(move, required):
    del required
    base = action_planner._move_sort_key(move)
    return (base[0], not move.is_spatial, *base[1:])


def _single_clone_first_witness(engine: FiveDEngine, seconds: float, move_key) -> dict:
    """Measure one deterministic canonical first branch without child deepcopies."""
    started = time.perf_counter()
    state = deepcopy(engine)
    state.timeline_manager.refresh_activity()
    state._ensure_current_action()
    path: list[MoveSpec] = []
    explored = 0
    termination = None
    first_candidate_ms = None

    while True:
        action = state._ensure_current_action()
        required = set(ActionRules.required_boards(
            action, state.timeline_manager.timelines
        ))
        if not required:
            if state.can_submit_action():
                first_candidate_ms = (time.perf_counter() - started) * 1000.0
                break
            termination = "royal_unsafe"
            break

        if time.perf_counter() - started >= seconds:
            termination = "time_budget"
            break
        if len(path) >= 64:
            termination = "move_depth_budget"
            break
        if explored >= 128:
            termination = "state_budget"
            break
        explored += 1

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
        if chosen is None:
            termination = "no_legal_move"
            break
        if not state.execute_action_move(chosen):
            termination = "execution_rejected"
            break
        path.append(MoveSpec.from_move(chosen))

    return {
        "budget": seconds,
        "first_candidate_ms": first_candidate_ms,
        "candidate_count": int(first_candidate_ms is not None),
        "first_candidate_depth": len(path) if first_candidate_ms is not None else None,
        "explored_states": explored,
        "termination": termination,
        "wall_ms": (time.perf_counter() - started) * 1000.0,
    }


def test_profile_optimized_deterministic_prefix_temp():
    engine = fixture.build_deterministic_complex_engine()
    report = _profile(engine, seconds=2.0)
    warnings.warn("PLANNER_OPTIMIZED_PROFILE_TEMP=" + json.dumps(report, sort_keys=True))
    assert report["candidate_count"] >= 1


def test_optimized_budget_matrix_temp():
    engine = fixture.build_deterministic_complex_engine()
    matrix = [_measure(engine, seconds) for seconds in (0.5, 1.0, 2.0, 5.0)]
    warnings.warn("PLANNER_OPTIMIZED_MATRIX_TEMP=" + json.dumps(matrix, sort_keys=True))
    assert any(row["candidate_count"] for row in matrix)


def test_optimized_32_required_board_matrix_temp():
    engine = fixture.build_deterministic_complex_engine()
    fixture._apply_recorded_action(engine, fixture.FINAL_ACTION, 34)
    required = ActionRules.required_boards(
        engine._ensure_current_action(), engine.timeline_manager.timelines
    )
    assert len(engine.timeline_manager.timelines) == 32
    assert len(required) == 32
    matrix = [_measure(engine, seconds) for seconds in (0.5, 1.0, 2.0, 5.0)]
    warnings.warn("PLANNER_32_REQUIRED_MATRIX_TEMP=" + json.dumps(matrix, sort_keys=True))


def test_single_clone_ordering_variants_temp():
    prefix = fixture.build_deterministic_complex_engine()
    final_state = deepcopy(prefix)
    fixture._apply_recorded_action(final_state, fixture.FINAL_ACTION, 34)
    variants = {
        "progress": _progress_key,
        "base_nonbranching": _base_key,
        "spatial_first": _spatial_key,
    }
    report = {}
    for name, key in variants.items():
        report[name] = {
            "required16": _single_clone_first_witness(prefix, 5.0, key),
            "required32": _single_clone_first_witness(final_state, 5.0, key),
        }
    warnings.warn("PLANNER_SINGLE_CLONE_VARIANTS_TEMP=" + json.dumps(report, sort_keys=True))
