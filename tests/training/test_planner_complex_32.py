"""Structural regression for the deterministic 32-required-board planner state."""
from __future__ import annotations

from copy import deepcopy

from src.ai.action_planner import (
    ActionPlanner,
    ActionSearchBudget,
    engine_state_signature,
    resolve_move_spec,
)
from src.engine import ActionRules
from tests.training import test_planner_complex_fixture as fixture


def test_optimized_32_required_state_returns_only_complete_legal_action():
    engine = fixture.build_deterministic_complex_engine()
    fixture._apply_recorded_action(engine, fixture.FINAL_ACTION, 34)
    required = ActionRules.required_boards(
        engine._ensure_current_action(), engine.timeline_manager.timelines
    )
    assert len(engine.timeline_manager.timelines) == 32
    assert len(required) == 32

    before = engine_state_signature(engine)
    result = ActionPlanner(ActionSearchBudget(
        max_states=64,
        max_actions=1,
        max_move_depth=64,
        max_seconds=None,
    )).search(engine)

    assert engine_state_signature(engine) == before
    assert result.candidates, result

    for candidate in result.candidates:
        assert candidate
        probe = deepcopy(engine)
        for spec in candidate:
            move = resolve_move_spec(probe, spec)
            assert probe.execute_action_move(move)
        remaining = ActionRules.required_boards(
            probe._ensure_current_action(), probe.timeline_manager.timelines
        )
        assert not remaining
        assert probe.can_submit_action()
        assert probe.submit_action()
