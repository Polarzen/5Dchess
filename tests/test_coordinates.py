"""Tests for canonical 5D coordinate and move primitives."""
import pytest

from src.engine.coordinates import BoardCoord, Square5D, Vector4D
from src.engine.move_generator import Move
from src.engine.piece import Piece
from src.utils.constants import ChessColor, PieceType


def test_board_coord_advances_half_moves():
    white_board = BoardCoord(0, 3, ChessColor.WHITE)
    black_board = white_board.next()
    assert black_board == BoardCoord(0, 3, ChessColor.BLACK)
    assert black_board.next() == BoardCoord(0, 4, ChessColor.WHITE)


def test_legacy_time_points_map_to_full_turn_and_side():
    assert BoardCoord.from_legacy_time_point(0, 6, ChessColor.WHITE) == BoardCoord(
        0, 3, ChessColor.WHITE
    )
    assert BoardCoord.from_legacy_time_point(0, 7, ChessColor.BLACK) == BoardCoord(
        0, 3, ChessColor.BLACK
    )
    assert BoardCoord(0, 3, ChessColor.WHITE).legacy_time_point == 6
    assert BoardCoord(0, 3, ChessColor.BLACK).legacy_time_point == 7


def test_legacy_time_point_rejects_inconsistent_side():
    with pytest.raises(ValueError, match="implies black"):
        BoardCoord.from_legacy_time_point(0, 5, ChessColor.WHITE)


def test_square_bounds_are_checked():
    board = BoardCoord(0, 0, ChessColor.WHITE)
    assert Square5D(board, 7, 7).x == 7
    with pytest.raises(ValueError):
        Square5D(board, 8, 0)


def test_vector_between_space_time_and_timeline():
    source = Square5D(BoardCoord(0, 5, ChessColor.WHITE), 4, 3)
    target = Square5D(BoardCoord(2, 2, ChessColor.WHITE), 6, 3)
    vector = Vector4D.between(source, target)
    assert vector == Vector4D(dx=2, dy=0, dt=-3, dl=2)
    assert vector.dimensions == 3
    assert vector.magnitudes == (2, 3, 2)


def test_vector_rejects_cross_side_geometry():
    source = Square5D(BoardCoord(0, 1, ChessColor.WHITE), 0, 0)
    target = Square5D(BoardCoord(0, 1, ChessColor.BLACK), 0, 1)
    with pytest.raises(ValueError):
        Vector4D.between(source, target)


def test_vector_primitive_step():
    assert Vector4D(4, -4, 0, 0).primitive() == Vector4D(1, -1, 0, 0)
    assert Vector4D(0, 0, -6, 3).primitive() == Vector4D(0, 0, -2, 1)


def test_move_uses_canonical_squares_and_legacy_accessors():
    piece = Piece(PieceType.ROOK, ChessColor.WHITE)
    source = Square5D(BoardCoord(0, 5, ChessColor.WHITE), 4, 4)
    destination = Square5D(BoardCoord(0, 2, ChessColor.WHITE), 4, 4)
    move = Move(
        piece=piece,
        source=source,
        destination=destination,
        is_branching=True,
        created_timeline=1,
    )

    assert move.vector == Vector4D(0, 0, -3, 0)
    assert move.is_time_travel
    assert not move.is_cross_timeline
    assert move.from_x == 4
    assert move.to_y == 4
    assert move.from_timeline_id == 0
    # Engine/storage compatibility still uses the legacy half-move index.
    assert move.from_time == 10
    assert move.to_time == 4
    assert move.created_timeline == 1
