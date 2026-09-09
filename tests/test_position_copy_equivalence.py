"""Semantic and isolation tests for the explicit Position copy path."""
from copy import deepcopy

import pytest

from src.ai import (
    ActionSearchBudget,
    RandomAI,
    StaleActionPlanError,
    apply_action_plan,
    engine_state_signature,
)
from src.engine import FiveDEngine, Position, TimelineManager
from src.utils.constants import ChessColor


def _legacy_copy(position: Position) -> Position:
    return deepcopy(position)


def _plan(engine: FiveDEngine):
    return RandomAI(
        engine.current_turn_color,
        seed=29,
        budget=ActionSearchBudget(
            max_states=256,
            max_actions=8,
            max_move_depth=8,
            max_seconds=1.0,
        ),
    ).plan_action(engine)


def test_position_copy_matches_deepcopy_and_isolates_mutable_fields():
    position = Position.initial(timeline_id=3, time_point=4)
    position.move_number = 17
    position.castling_rights["white_kingside"] = False
    position.en_passant_target = (4, 5)
    position.unmoved_pawns.add((3, 3))

    expected = deepcopy(position)
    clone = position.copy()

    assert clone == expected
    assert clone is not position
    assert clone.board is not position.board
    assert all(a is not b for a, b in zip(clone.board, position.board))
    assert clone.castling_rights is not position.castling_rights
    assert clone.unmoved_pawns is not position.unmoved_pawns

    clone.board[0][0] = ""
    clone.castling_rights["black_kingside"] = False
    clone.unmoved_pawns.add((0, 0))
    assert position.board[0][0] != clone.board[0][0]
    assert position.castling_rights["black_kingside"] is True
    assert (0, 0) not in position.unmoved_pawns


def test_position_copy_matches_legacy_engine_action_state(monkeypatch):
    optimized = FiveDEngine()
    legacy = deepcopy(optimized)
    plan = _plan(optimized)

    with monkeypatch.context() as patch:
        patch.setattr(Position, "copy", _legacy_copy)
        assert apply_action_plan(legacy, plan)

    assert apply_action_plan(optimized, plan)
    assert engine_state_signature(optimized) == engine_state_signature(legacy)
    assert optimized.game_state == legacy.game_state
    assert optimized.move_counter == legacy.move_counter
    assert len(optimized.action_history) == len(legacy.action_history)


def test_timeline_branch_copies_history_without_aliasing():
    manager = TimelineManager(max_timelines=4)
    parent = manager.create_initial_timeline()
    first = Position.initial(timeline_id=0, time_point=0)
    second = first.copy()
    second.time_point = 1
    second.turn = ChessColor.BLACK
    second.castling_rights["white_kingside"] = False
    parent.positions = {0: first, 1: second}

    branch = manager.create_branch(
        parent_id=0,
        branch_turn=1,
        branch_move_id=7,
        target_time=1,
        creator=ChessColor.WHITE,
    )
    assert branch is not None
    assert branch.timeline_id == 1
    for time_point in (0, 1):
        source = parent.positions[time_point]
        copied = branch.positions[time_point]
        assert copied.timeline_id == branch.timeline_id
        assert copied.board == source.board
        assert copied.board is not source.board
        assert copied.castling_rights is not source.castling_rights
        assert copied.unmoved_pawns is not source.unmoved_pawns

    branch.positions[1].board[0][0] = ""
    branch.positions[1].castling_rights["black_kingside"] = False
    assert parent.positions[1].board[0][0] != branch.positions[1].board[0][0]
    assert parent.positions[1].castling_rights["black_kingside"] is True


def test_position_copy_change_does_not_weaken_stale_plan_guard():
    engine = FiveDEngine()
    plan = _plan(engine)
    position = engine.get_current_position()
    move = engine.get_legal_moves(position)[0]
    assert engine.execute_action_move(move)

    with pytest.raises(StaleActionPlanError):
        apply_action_plan(engine, plan)
