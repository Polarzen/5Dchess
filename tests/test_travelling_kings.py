"""Royal safety after a King leaves or joins another timeline."""
from copy import deepcopy

import pytest

from src.engine import ActionRules, BoardCoord, FiveDEngine, Position, Timeline
from src.engine.move_validator import MoveValidator
from src.engine.royal_rules import RoyalRules
from src.utils.constants import ChessColor


def position(lane, time, pieces):
    board = [["" for _ in range(8)] for _ in range(8)]
    for (x, y), char in pieces.items():
        board[y][x] = char
    return Position(board=board, timeline_id=lane, time_point=time,
                    turn=BoardCoord.legacy_side_for_time_point(time), unmoved_pawns=set())


def engine_with(*positions):
    engine = FiveDEngine()
    engine.timeline_manager.timelines = {}
    for pos in positions:
        engine.timeline_manager.timelines.setdefault(pos.timeline_id, Timeline(pos.timeline_id)).add_position(pos)
    engine.current_turn_color = positions[-1].turn
    engine.current_action = ActionRules.begin(engine.current_turn_color, engine.timeline_manager.timelines)
    return engine


@pytest.mark.parametrize("color", list(ChessColor))
def test_king_departure_does_not_freeze_other_pieces_next_turn(color):
    flip = color == ChessColor.BLACK
    def pieces():
        return {(x, 7-y if flip else y): c.swapcase() if flip else c
                for (x, y), c in {(2, 6): 'K', (0, 6): 'P', (7, 0): 'k', (7, 1): 'p'}.items()}
    start = 1 if flip else 0
    source = position(0, start, pieces())
    other_pieces = pieces()
    del other_pieces[(2, 1 if flip else 6)]
    other_pieces[(6, 1 if flip else 6)] = 'k' if flip else 'K'
    dest = position(1, start, other_pieces)
    engine = engine_with(source, dest)
    original = deepcopy(source.board)
    jump = next(m for m in engine.get_legal_moves_from_square(source, 2, 1 if flip else 6)
                if m.destination.timeline == 1 and m.to_x == 2 and m.to_y == (1 if flip else 6))
    assert engine.execute_action_move(jump)
    assert engine.can_submit_action()
    assert engine.submit_action(evaluate_outcome=False)
    for lane in [0, 1]:
        timeline = engine.timeline_manager.timelines[lane]
        pos = timeline.positions[timeline.latest_time]
        reply = next(m for m in engine.get_legal_moves_from_square(pos, 7, 6 if flip else 1)
                     if m.is_spatial and m.to_y == (5 if flip else 2))
        assert engine.execute_action_move(reply)
    assert engine.submit_action(evaluate_outcome=False)
    timeline = engine.timeline_manager.timelines[0]
    pos = timeline.positions[timeline.latest_time]
    assert pos.find_king(color) is None
    moves = engine.get_legal_moves_from_square(pos, 0, 1 if flip else 6)
    advance = next((m for m in moves if m.is_spatial and m.to_y == (2 if flip else 5)), None)
    assert advance is not None, 'A King departure must not immobilize its remaining Pawn'
    assert engine.execute_action_move(advance)
    assert source.board == original


@pytest.mark.parametrize("color", list(ChessColor))
def test_every_same_color_king_is_checked_locally_and_at_submission(color):
    chars = {(0, 0): 'K', (4, 6): 'K', (4, 2): 'r', (7, 7): 'k', (7, 5): 'P'}
    if color == ChessColor.BLACK:
        chars = {coord: char.swapcase() for coord, char in chars.items()}
    pos = position(0, 0 if color == ChessColor.WHITE else 1, chars)
    engine = engine_with(pos)
    rules = RoyalRules(engine.timeline_manager.timelines)
    assert len(rules.king_squares(color)) == 2
    assert rules.is_in_check(color)
    assert MoveValidator().is_king_in_check(pos, color)
    assert not MoveValidator()._local_king_safe(pos, color)
    # The first King is safe, but ignoring the second cannot permit a quiet Pawn move.
    assert not [m for m in engine.get_legal_moves_from_square(pos, 7, 5) if m.is_spatial]
    successor = engine._build_successor(pos)
    engine.timeline_manager.timelines[0].add_position(successor)
    assert not engine.can_submit_action()


def test_king_cannot_arrive_under_attack_beside_an_already_safe_king():
    source = position(0, 0, {(4, 6): 'K', (7, 0): 'k'})
    dest = position(1, 0, {(0, 0): 'K', (4, 2): 'r', (7, 7): 'k'})
    engine = engine_with(source, dest)
    assert not [m for m in engine.get_legal_moves_from_square(source, 4, 6)
                if m.destination.board == BoardCoord(1, 0, ChessColor.WHITE)
                and (m.to_x, m.to_y) == (4, 6)]
