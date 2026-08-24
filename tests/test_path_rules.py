"""Tests for 4D sliding-piece path tracing."""
import pytest

from src.engine.coordinates import BoardCoord, Square5D
from src.engine.path_rules import PathBlockReason, PathRules
from src.utils.constants import ChessColor, PieceType


class FakeBoard:
    def __init__(self, occupied=()):
        self.occupied = set(occupied)

    def get_piece(self, x, y):
        return object() if (x, y) in self.occupied else None


def square(timeline, turn, x, y):
    return Square5D(
        BoardCoord(timeline, turn, ChessColor.WHITE),
        x,
        y,
    )


def test_rook_spatial_path_excludes_endpoints():
    source = square(0, 5, 0, 3)
    destination = square(0, 5, 4, 3)

    assert PathRules.intermediate_squares(
        PieceType.ROOK, source, destination
    ) == (
        square(0, 5, 1, 3),
        square(0, 5, 2, 3),
        square(0, 5, 3, 3),
    )


def test_bishop_can_trace_across_space_and_time():
    source = square(0, 5, 1, 2)
    destination = square(0, 2, 4, 2)

    assert PathRules.intermediate_squares(
        PieceType.BISHOP, source, destination
    ) == (
        square(0, 4, 2, 2),
        square(0, 3, 3, 2),
    )


def test_queen_can_trace_a_four_dimensional_diagonal():
    source = square(0, 5, 1, 1)
    destination = square(3, 2, 4, 4)

    assert PathRules.intermediate_squares(
        PieceType.QUEEN, source, destination
    ) == (
        square(1, 4, 2, 2),
        square(2, 3, 3, 3),
    )


def test_single_step_slider_has_no_intermediate_squares():
    source = square(0, 1, 3, 3)
    destination = square(0, 1, 4, 3)

    assert PathRules.intermediate_squares(
        PieceType.ROOK, source, destination
    ) == ()
    assert PathRules.is_clear(
        PieceType.ROOK,
        source,
        destination,
        lambda _: None,
    )


def test_non_slider_is_rejected():
    source = square(0, 1, 1, 1)
    destination = square(0, 1, 3, 2)

    with pytest.raises(ValueError, match="not a sliding piece"):
        PathRules.intermediate_squares(PieceType.KNIGHT, source, destination)


def test_invalid_slider_geometry_is_rejected():
    source = square(0, 5, 1, 2)
    destination = square(0, 3, 4, 2)

    with pytest.raises(ValueError, match="invalid BISHOP movement geometry"):
        PathRules.intermediate_squares(PieceType.BISHOP, source, destination)


def test_missing_intermediate_board_blocks_path():
    source = square(0, 5, 1, 2)
    destination = square(0, 2, 4, 2)
    boards = {
        BoardCoord(0, 4, ChessColor.WHITE): FakeBoard(),
        # T3 intentionally missing.
    }

    blocker = PathRules.first_blocker(
        PieceType.BISHOP,
        source,
        destination,
        boards.get,
    )

    assert blocker is not None
    assert blocker.square == square(0, 3, 3, 2)
    assert blocker.reason == PathBlockReason.MISSING_BOARD
    assert not PathRules.is_clear(
        PieceType.BISHOP, source, destination, boards.get
    )


def test_occupied_intermediate_square_blocks_path():
    source = square(0, 5, 1, 1)
    destination = square(3, 2, 4, 4)
    boards = {
        BoardCoord(1, 4, ChessColor.WHITE): FakeBoard(),
        BoardCoord(2, 3, ChessColor.WHITE): FakeBoard({(3, 3)}),
    }

    blocker = PathRules.first_blocker(
        PieceType.QUEEN,
        source,
        destination,
        boards.get,
    )

    assert blocker is not None
    assert blocker.square == square(2, 3, 3, 3)
    assert blocker.reason == PathBlockReason.OCCUPIED


def test_clear_path_requires_all_intermediate_boards_and_empty_squares():
    source = square(0, 5, 1, 1)
    destination = square(3, 2, 4, 4)
    boards = {
        BoardCoord(1, 4, ChessColor.WHITE): FakeBoard(),
        BoardCoord(2, 3, ChessColor.WHITE): FakeBoard(),
    }

    assert PathRules.first_blocker(
        PieceType.QUEEN, source, destination, boards.get
    ) is None
    assert PathRules.is_clear(
        PieceType.QUEEN, source, destination, boards.get
    )
