"""Standard-start castling must check the King origin, transit and destination."""
import pytest

from src.engine import ActionRules, FiveDEngine, Position, Timeline
from src.utils.constants import ChessColor


def castle_engine(color, kingside, attack_x=None):
    row, enemy_row = (7, 0) if color == ChessColor.WHITE else (0, 7)
    own_king, own_rook, enemy_king, enemy_rook = (
        ('K', 'R', 'k', 'r') if color == ChessColor.WHITE else ('k', 'r', 'K', 'R'))
    board = [[''] * 8 for _ in range(8)]
    board[row][4], board[row][7 if kingside else 0] = own_king, own_rook
    board[enemy_row][7] = enemy_king
    if attack_x is not None:
        board[enemy_row][attack_x] = enemy_rook
    pos = Position(board, color, 0, 0 if color == ChessColor.WHITE else 1)
    engine = FiveDEngine()
    engine.timeline_manager.timelines = {0: Timeline(0, positions={pos.time_point: pos})}
    engine.current_turn_color = color
    engine.current_action = ActionRules.begin(color, engine.timeline_manager.timelines)
    return engine, pos


@pytest.mark.parametrize('color', list(ChessColor))
@pytest.mark.parametrize('kingside', [True, False])
@pytest.mark.parametrize('attack', ['origin', 'transit', 'destination', None])
def test_castling_king_route_safety(color, kingside, attack):
    destination, transit = (6, 5) if kingside else (2, 3)
    attack_x = {'origin': 4, 'transit': transit, 'destination': destination}.get(attack)
    engine, pos = castle_engine(color, kingside, attack_x)
    original = [row[:] for row in pos.board]
    castles = [m for m in engine.get_legal_moves_from_square(pos, 4, 7 if color == ChessColor.WHITE else 0)
               if m.is_castling]
    assert bool(castles) == (attack is None)
    if castles:
        move = castles[0]
        assert engine.execute_action_move(move)
        assert engine.submit_action(evaluate_outcome=False)
        after = engine.get_current_position()
        assert after.get_piece(destination, move.to_y) == move.piece
        assert after.get_piece(transit, move.to_y).piece_type.value == 'R'
    assert pos.board == original


@pytest.mark.parametrize('color', list(ChessColor))
def test_attacked_queenside_rook_and_b_file_do_not_forbid_castling(color):
    for attack_x in (0, 1):
        engine, pos = castle_engine(color, False, attack_x)
        assert any(m.is_castling for m in engine.get_legal_moves(pos))


@pytest.mark.parametrize('color', list(ChessColor))
def test_castling_rights_remain_required(color):
    engine, pos = castle_engine(color, True)
    pos.castling_rights[f'{color.value}_kingside'] = False
    assert not any(m.is_castling for m in engine.get_legal_moves(pos))
