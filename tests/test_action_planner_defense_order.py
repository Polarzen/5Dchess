"""Complete-Action regression for the captured 19-required-board failure."""
import gzip
import json
from pathlib import Path

import pytest

import src.ai.action_planner as planning
from src.ai.action_planner import (
    AIActionPlan, ActionPlanner, _PRODUCTION_HYBRID_BUDGET,
    apply_action_plan, engine_state_signature,
)
from src.data.archive import GameArchive
from src.engine import ActionRules, FiveDEngine, Position, Timeline
from src.engine.coordinates import BoardCoord
from src.engine.royal_rules import RoyalRules
from src.utils.constants import ChessColor, PieceType


def _captured(name='easy20_nineteen_required_state'):
    path = Path(__file__).parent / f'fixtures/{name}.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(path.read_bytes())))
    del engine._replay_origin
    return engine


def test_active_rewind_defers_uncapturable_required_attacker():
    engine = _captured('easy20_active_rewind_state')
    before = engine_state_signature(engine)
    planner = ActionPlanner(_PRODUCTION_HYBRID_BUDGET)
    result = planner.search(engine)
    assert result.candidates and len(result.candidates[0]) == 1
    assert not planner._defense_order_active  # small roots keep ordinary MRV
    child = engine.clone_for_simulation()
    apply_action_plan(child, AIActionPlan(engine.current_turn_color, result.candidates[0], before))
    assert child.action_history[-1].submitted
    assert child.timeline_manager.timelines[1].latest_time == engine.timeline_manager.timelines[1].latest_time
    assert engine_state_signature(engine) == before


def test_active_rewind_with_one_required_board():
    engine = _captured('control43_active_rewind_state')
    before = engine_state_signature(engine)
    assert len(engine.get_required_action_boards()) == 1
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert result.candidates and len(result.candidates[0]) == 1
    child = engine.clone_for_simulation()
    apply_action_plan(child, AIActionPlan(engine.current_turn_color, result.candidates[0], before))
    assert child.action_history[-1].submitted
    assert engine_state_signature(engine) == before


@pytest.mark.parametrize('fixture', ['easy20_pinned_rewind_state', 'easy20_pinned_rewind_large_state'])
def test_pinned_capture_does_not_hide_active_rewind(fixture):
    engine = _captured(fixture)
    before = engine_state_signature(engine)
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert result.candidates and len(result.candidates[0]) == 1
    for candidate in result.candidates:
        child = engine.clone_for_simulation()
        apply_action_plan(child, AIActionPlan(engine.current_turn_color, candidate, before))
        assert child.action_history[-1].submitted
    assert engine_state_signature(engine) == before


def test_large_mutable_king_escape_candidates_replay():
    engine = _captured('easy20_king_escape_state')
    before = engine_state_signature(engine)
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert result.candidates
    assert result.explored_states <= 1024 and len(result.candidates) <= 24
    for candidate in result.candidates:
        assert len(candidate) <= 32
        child = engine.clone_for_simulation()
        apply_action_plan(child, AIActionPlan(engine.current_turn_color, candidate, before))
        assert child.action_history[-1].submitted
    assert engine_state_signature(engine) == before


def test_risky_king_moves_are_deferred_but_retained():
    engine = _captured('easy20_king_escape_state')
    before = engine_state_signature(engine)
    position = engine._resolve_position(next(b for b in engine.get_required_action_boards() if b.timeline == 0))
    moves = sorted((m for m in engine.get_legal_moves(position)
                    if m.piece.piece_type == PieceType.KING), key=planning._move_sort_key)
    tracker = planning._BudgetTracker(planning.ActionSearchBudget(max_seconds=30))
    ordered = list(planning._safe_king_moves_first(engine, moves, tracker, None))
    assert {planning.MoveSpec.from_move(m) for m, _ in ordered} == {planning.MoveSpec.from_move(m) for m in moves}
    risks = []
    for move, child in ordered:
        if child is None:
            child = engine.clone_for_simulation()
            assert child.execute_action_move(move)
        risks.append(RoyalRules(child.timeline_manager.timelines).is_in_check(engine.current_turn_color))
    assert False in risks and True in risks
    assert risks == sorted(risks)
    assert engine_state_signature(engine) == before


def test_late_king_safety_query_yields_no_prepared_child(monkeypatch):
    engine = _captured('easy20_king_escape_state')
    position = engine._resolve_position(next(b for b in engine.get_required_action_boards() if b.timeline == 0))
    moves = [m for m in engine.get_legal_moves(position) if m.piece.piece_type == PieceType.KING]
    now = [0.0]
    monkeypatch.setattr(planning.time, 'monotonic', lambda: now[0])
    def delayed_safety(self, color):
        now[0] = 6.0
        return False
    monkeypatch.setattr(RoyalRules, 'is_in_check', delayed_safety)
    tracker = planning._BudgetTracker(_PRODUCTION_HYBRID_BUDGET)
    assert not list(planning._safe_king_moves_first(engine, moves, tracker, None))
    assert tracker.termination_reason == 'time_budget'


def test_rewind_priority_includes_future_optional_sources():
    def position(lane, time, pieces):
        board = [[''] * 8 for _ in range(8)]
        for x, y, symbol in pieces:
            board[y][x] = symbol
        return Position(board=board, timeline_id=lane, time_point=time,
                        turn=BoardCoord.legacy_side_for_time_point(time), unmoved_pawns=set())
    engine = FiveDEngine()
    manager = engine.timeline_manager
    manager.timelines = {
        0: Timeline(0, positions={
            0: position(0, 0, [(7, 7, 'K'), (7, 0, 'k')]),
            2: position(0, 2, [(0, 0, 'r'), (7, 0, 'k')]),
        }),
        1: Timeline(1, owner=ChessColor.WHITE,
                    positions={3: position(1, 3, [(0, 0, 'K'), (7, 0, 'k')])}),
        2: Timeline(2, owner=ChessColor.WHITE, positions={2: position(2, 2, [])}),
        -1: Timeline(-1, owner=ChessColor.BLACK, positions={2: position(-1, 2, [])}),
        -2: Timeline(-2, owner=ChessColor.BLACK,
                     positions={4: position(-2, 4, [(0, 7, 'Q'), (7, 7, 'K'), (7, 0, 'k')])}),
    }
    manager._next_positive_id = 3
    manager._next_negative_id = -3
    engine.current_action = ActionRules.begin(ChessColor.WHITE, manager.timelines)
    required = ActionRules.required_boards(engine.current_action, manager.timelines)
    assert len(required) == 3 and all(board.timeline != -2 for board in required)
    before = engine_state_signature(engine)
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert result.candidates and len(result.candidates[0]) == 1
    assert result.candidates[0][0].source.timeline == -2
    child = engine.clone_for_simulation()
    apply_action_plan(child, AIActionPlan(engine.current_turn_color, result.candidates[0], before))
    assert child.timeline_manager.timelines[0].latest_time == 2
    assert child.action_history[-1].submitted
    assert engine_state_signature(engine) == before


def test_large_defense_candidates_replay_and_strategy_does_not_leak():
    engine = _captured()
    before = engine_state_signature(engine)
    planner = ActionPlanner(_PRODUCTION_HYBRID_BUDGET)
    result = planner.search(engine)
    assert result.candidates
    assert result.explored_states <= 1024 and len(result.candidates) <= 24
    for path in result.candidates:
        assert len(path) <= 32
        child = engine.clone_for_simulation()
        apply_action_plan(child, AIActionPlan(engine.current_turn_color, path, before))
        assert child.action_history[-1].submitted
    assert engine_state_signature(engine) == before
    assert planner._defense_order_active
    fresh = FiveDEngine()
    assert planner.search(fresh).candidates
    assert not planner._defense_order_active


def test_late_defense_preparation_is_not_a_terminal_proof(monkeypatch):
    engine = _captured()
    before = engine_state_signature(engine)
    now = [0.0]
    monkeypatch.setattr(planning.time, 'monotonic', lambda: now[0])
    for name in ('prove_direct_threat', 'prove_required_board_threat', 'prove_required_board_immobile'):
        monkeypatch.setattr(planning, name, lambda *args: None)
    original = planning.RoyalRules.threats_against
    def delayed_threats(self, color):
        result = original(self, color)
        now[0] = 6.0
        return result
    monkeypatch.setattr(planning.RoyalRules, 'threats_against', delayed_threats)
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert not result.candidates and result.termination_reason == 'time_budget'
    assert result.failed_state_cache_hits == 0
    assert engine_state_signature(engine) == before


def test_late_rewind_move_generation_is_not_a_terminal_proof(monkeypatch):
    engine = _captured('easy20_active_rewind_state')
    before = engine_state_signature(engine)
    now = [0.0]
    monkeypatch.setattr(planning.time, 'monotonic', lambda: now[0])
    original = FiveDEngine.get_legal_moves
    def delayed_moves(self, position=None):
        moves = original(self, position)
        now[0] = 6.0
        return moves
    monkeypatch.setattr(FiveDEngine, 'get_legal_moves', delayed_moves)
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert not result.candidates and result.termination_reason == 'time_budget'
    assert result.failed_state_cache_hits == 0
    assert engine_state_signature(engine) == before
