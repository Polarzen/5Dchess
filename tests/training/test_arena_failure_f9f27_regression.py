"""Deterministic regression for the real checkpoint Arena failure f9f27a86.

The fixture is the complete canonical Action trace captured by GitHub Actions
run 33813126560.  Replaying it does not depend on the model, RNG, wall-clock
budgets, or direct engine mutation.  Every Move is resolved from the engine's
current canonical legal Move set and every Action is submitted normally.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.ai.action_planner import (
    ActionPlanner,
    ActionSearchBudget,
    MoveSpec,
    engine_state_signature,
    resolve_move_spec,
)
from src.engine import ActionRules, BoardCoord, FiveDEngine, Square5D
from src.engine.action_search import ActionSearch
from src.training.arena import _state_signature_sha256
from src.utils.constants import ChessColor, PieceType


TRACE_PATH = Path(__file__).parent / "fixtures" / "arena_failure_f9f27_trace.json"
TARGET_SHA = "f9f27a862e3213dcef554db5045e846d58f6c887821470bc75b797b91f24f637"


def _move_spec(raw: dict) -> MoveSpec:
    source_timeline, source_turn, source_side, source_x, source_y = raw["source"]
    dest_timeline, dest_turn, dest_side, dest_x, dest_y = raw["destination"]
    promotion = PieceType(raw["promotion"]) if raw.get("promotion") else None
    return MoveSpec(
        Square5D(
            BoardCoord(source_timeline, source_turn, ChessColor(source_side)),
            source_x,
            source_y,
        ),
        Square5D(
            BoardCoord(dest_timeline, dest_turn, ChessColor(dest_side)),
            dest_x,
            dest_y,
        ),
        promotion,
    )


def build_failure_engine() -> FiveDEngine:
    trace = json.loads(TRACE_PATH.read_text(encoding="utf-8"))
    engine = FiveDEngine()
    for action_index, action_specs in enumerate(trace):
        for raw in action_specs:
            move = resolve_move_spec(engine, _move_spec(raw))
            assert engine.execute_action_move(move), (action_index, raw)
        assert engine.can_submit_action(), action_index
        assert engine.submit_action(), action_index
    return engine


@pytest.fixture(scope="module")
def failure_engine() -> FiveDEngine:
    return build_failure_engine()


def _apply_candidate(engine: FiveDEngine, candidate) -> None:
    for spec in candidate:
        assert engine.execute_action_move(resolve_move_spec(engine, spec))
    assert not ActionRules.required_boards(
        engine._ensure_current_action(), engine.timeline_manager.timelines
    )
    assert engine.can_submit_action()
    assert engine.submit_action()


def test_captured_failure_trace_replays_exact_state(failure_engine):
    required = ActionRules.required_boards(
        failure_engine._ensure_current_action(),
        failure_engine.timeline_manager.timelines,
    )

    assert _state_signature_sha256(failure_engine) == TARGET_SHA
    assert failure_engine.current_turn_color is ChessColor.BLACK
    assert failure_engine.move_counter == 57
    assert len(failure_engine.timeline_manager.timelines) == 12
    assert len(required) == 2


def test_action_planner_finds_complete_two_board_candidate_without_mutating_caller(
    failure_engine,
):
    before = engine_state_signature(failure_engine)
    result = ActionPlanner(ActionSearchBudget(
        max_states=8,
        max_actions=1,
        max_move_depth=8,
        max_seconds=None,
    )).search(failure_engine)

    assert engine_state_signature(failure_engine) == before
    assert result.candidates, result
    assert len(result.candidates[0]) == 1

    probe = deepcopy(failure_engine)
    _apply_candidate(probe, result.candidates[0])


def test_outcome_action_search_finds_same_one_move_witness_without_wall_clock(
    failure_engine,
):
    before = engine_state_signature(failure_engine)
    result = ActionSearch(
        max_states=8,
        max_depth=8,
        max_seconds=None,
    ).find_legal_completion(failure_engine)

    assert engine_state_signature(failure_engine) == before
    assert result.has_legal_action, result
    assert result.termination_reason is None
    assert len(result.witness) == 1

    probe = deepcopy(failure_engine)
    specs = tuple(MoveSpec.from_move(move) for move in result.witness)
    _apply_candidate(probe, specs)
