"""Temporary deterministic branch-heavy trace generator for planner Plan B.

This uses only canonical ActionPlanner candidates and apply_action_plan.  It has
no neural model, randomness, or wall-clock search budget.  The file is removed
after a replayable fixed trace has been captured from CI.
"""
from __future__ import annotations

import json
import warnings

import src.ai.action_planner as action_planner
from src.ai.action_planner import (
    AIActionPlan,
    ActionPlanner,
    ActionSearchBudget,
    apply_action_plan,
    engine_state_signature,
)
from src.engine import ActionRules, FiveDEngine
from src.utils.constants import GameState


def _branching_first_key(move):
    """Deterministically prefer branching transitions for fixture generation."""
    return (
        not bool(move.is_branching),
        move.destination.board.timeline,
        move.destination.board.turn,
        move.destination.board.side.value,
        move.destination.y,
        move.destination.x,
        move.source.board.timeline,
        move.source.board.turn,
        move.source.board.side.value,
        move.source.y,
        move.source.x,
        move.promotion.value if move.promotion else "",
        bool(move.is_cross_timeline),
    )


def _square(square):
    return [
        square.board.timeline,
        square.board.turn,
        square.board.side.value,
        square.x,
        square.y,
    ]


def _spec(spec):
    return {
        "source": _square(spec.source),
        "destination": _square(spec.destination),
        "promotion": spec.promotion.value if spec.promotion else None,
    }


def test_generate_deterministic_complex_fixture_trace(monkeypatch):
    monkeypatch.setattr(action_planner, "_move_sort_key", _branching_first_key)
    engine = FiveDEngine()
    budget = ActionSearchBudget(
        max_states=20000,
        max_actions=1,
        max_move_depth=64,
        max_seconds=None,
    )
    trace = []
    states = []

    # Generate a branch-heavy but fully canonical deterministic game.  Stop as
    # soon as the fixture reaches the requested complexity; the captured trace
    # will later replace this generator.
    for action_index in range(80):
        if engine.game_state != GameState.PLAYING:
            break
        required_before = len(ActionRules.required_boards(
            engine._ensure_current_action(), engine.timeline_manager.timelines
        ))
        result = ActionPlanner(budget).search(engine)
        assert result.candidates, {
            "action_index": action_index,
            "timelines": len(engine.timeline_manager.timelines),
            "required": required_before,
            "termination": result.termination_reason,
            "explored": result.explored_states,
        }
        candidate = result.candidates[0]
        trace.append([_spec(spec) for spec in candidate])
        plan = AIActionPlan(
            color=engine.current_turn_color,
            moves=candidate,
            start_signature=engine_state_signature(engine),
        )
        apply_action_plan(engine, plan)
        action = engine._ensure_current_action()
        required_after = len(ActionRules.required_boards(
            action, engine.timeline_manager.timelines
        ))
        states.append({
            "action": action_index,
            "timelines": len(engine.timeline_manager.timelines),
            "required_next": required_after,
            "move_counter": engine.move_counter,
            "moves": len(candidate),
            "explored": result.explored_states,
            "termination": result.termination_reason,
        })
        if len(engine.timeline_manager.timelines) >= 24 and required_after >= 20:
            break

    telemetry = {
        "trace": trace,
        "states": states,
        "final_timelines": len(engine.timeline_manager.timelines),
        "final_required": len(ActionRules.required_boards(
            engine._ensure_current_action(), engine.timeline_manager.timelines
        )),
        "actions": len(trace),
        "move_counter": engine.move_counter,
    }
    warnings.warn("DETERMINISTIC_COMPLEX_FIXTURE_TRACE=" + json.dumps(
        telemetry, sort_keys=True, separators=(",", ":")
    ))
    assert telemetry["final_timelines"] >= 24, telemetry
    assert telemetry["final_required"] >= 20, telemetry
