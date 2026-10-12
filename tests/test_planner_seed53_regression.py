"""Regression for the seed 53 complete-Action planner failure state."""
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


_FIXTURE = Path(__file__).parent / "fixtures" / "seed53_planner_state.json.gz"


def _seed53_engine():
    payload = json.loads(gzip.decompress(_FIXTURE.read_bytes()).decode("utf-8"))
    engine = GameArchive.restore(payload)
    # GameArchive restore attaches replay-only origin metadata. Planner simulation
    # intentionally rejects unknown dynamic engine fields, so the planner fixture
    # represents only the canonical rule state captured at the failure boundary.
    if hasattr(engine, "_replay_origin"):
        delattr(engine, "_replay_origin")
    return engine


def test_seed53_optional_to_required_progress_reaches_complete_action_early():
    engine = _seed53_engine()
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

    assert len(required) == 2
    optional_progress_moves = []
    for board in movable:
        if board in required:
            continue
        position = engine._resolve_position(board)
        if position is None:
            continue
        optional_progress_moves.extend(
            move
            for move in engine.get_legal_moves(position)
            if move.destination.board in required
        )
    assert optional_progress_moves

    result = ActionPlanner(ActionSearchBudget(
        max_states=1024,
        max_actions=1,
        max_move_depth=32,
        max_seconds=None,
    )).search(engine)

    assert engine_state_signature(engine) == before
    assert result.candidates
    # The captured production failure exhausted all 1024 states with no Action.
    # A completion-aware ordering should reach the shallow witness well before
    # that boundary; leave margin for deterministic tie-order changes.
    assert result.explored_states <= 64

    candidate = result.candidates[0]
    assert candidate[0].source.board not in required
    assert candidate[0].destination.board in required

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
