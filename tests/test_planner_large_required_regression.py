"""Regression for the seed 53 high-branch Action planning state."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from src.ai import (
    AIActionPlan,
    ActionPlanner,
    ActionSearchBudget,
    apply_action_plan,
    engine_state_signature,
)
from src.data.archive import GameArchive
from src.engine.action import ActionRules


_FIXTURE = Path(__file__).parent / "fixtures" / "seed53_large_required_state.json.gz"


def _large_required_engine():
    payload = json.loads(gzip.decompress(_FIXTURE.read_bytes()).decode("utf-8"))
    engine = GameArchive.restore(payload)

    # The archive boundary is JSON-normalized, while an in-memory capture uses
    # integer timeline keys.  Verify both the archive round-trip and the state
    # signature before removing replay-only metadata for planner simulation.
    captured = GameArchive.capture(engine)
    normalized_capture = json.loads(json.dumps(captured, ensure_ascii=False))
    assert normalized_capture == payload
    round_tripped = GameArchive.restore(captured)
    assert engine_state_signature(round_tripped) == engine_state_signature(engine)

    assert hasattr(engine, "_replay_origin")
    delattr(engine, "_replay_origin")
    return engine


def test_seed53_large_required_state_finds_action_under_production_budget():
    engine = _large_required_engine()
    before = engine_state_signature(engine)
    action = engine._ensure_current_action()
    required = set(ActionRules.required_boards(
        action,
        engine.timeline_manager.timelines,
    ))
    movable = ActionRules.movable_boards(
        action,
        engine.timeline_manager.timelines,
    )

    root_branch = sum(
        len(engine.get_legal_moves(position))
        for board in movable
        if (position := engine._resolve_position(board)) is not None
    )
    assert len(required) == 14
    assert len(required) > 2
    assert root_branch == 1639
    assert root_branch > 1000
    assert engine.move_counter == 99
    assert len(engine.action_history) == 77

    result = ActionPlanner(ActionSearchBudget(
        max_states=1024,
        max_actions=24,
        max_move_depth=32,
        max_seconds=5.0,
    )).search(engine)

    assert engine_state_signature(engine) == before
    assert result.explored_states < 1024
    assert result.candidates

    candidate = result.candidates[0]
    plan = AIActionPlan(
        color=engine.current_turn_color,
        moves=candidate,
        start_signature=before,
    )
    applied_engine = engine.clone_for_simulation()
    applied = apply_action_plan(applied_engine, plan)
    assert applied
    assert applied_engine.action_history[-1].submitted
    assert applied_engine.current_turn_color != engine.current_turn_color
    assert engine_state_signature(engine) == before
