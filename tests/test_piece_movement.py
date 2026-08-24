"""Tests for pure 4D piece movement geometry."""
import pytest

from src.engine.coordinates import Vector4D
from src.engine.piece_movement import PieceMovementRules
from src.utils.constants import PieceType


@pytest.mark.parametrize("vector", [
    Vector4D(5, 0, 0, 0),
    Vector4D(0, -3, 0, 0),
    Vector4D(0, 0, -4, 0),
    Vector4D(0, 0, 0, 2),
])
def test_rook_accepts_exactly_one_axis(vector):
    assert PieceMovementRules.is_valid(PieceType.ROOK, vector)


@pytest.mark.parametrize("vector", [
    Vector4D(1, 1, 0, 0),
    Vector4D(0, 0, 2, -2),
    Vector4D(),
])
def test_rook_rejects_non_rook_geometry(vector):
    assert not PieceMovementRules.is_valid(PieceType.ROOK, vector)


@pytest.mark.parametrize("vector", [
    Vector4D(3, -3, 0, 0),
    Vector4D(4, 0, -4, 0),
    Vector4D(0, 2, 0, 2),
    Vector4D(0, 0, -5, 5),
])
def test_bishop_accepts_equal_distance_on_two_axes(vector):
    assert PieceMovementRules.is_valid(PieceType.BISHOP, vector)


@pytest.mark.parametrize("vector", [
    Vector4D(3, 0, 0, 0),
    Vector4D(3, 2, 0, 0),
    Vector4D(2, 2, 2, 0),
])
def test_bishop_rejects_wrong_dimension_or_distance(vector):
    assert not PieceMovementRules.is_valid(PieceType.BISHOP, vector)


@pytest.mark.parametrize("vector", [
    Vector4D(4, 0, 0, 0),
    Vector4D(4, -4, 0, 0),
    Vector4D(2, -2, 2, 0),
    Vector4D(3, 3, -3, 3),
])
def test_queen_accepts_equal_distance_across_one_to_four_axes(vector):
    assert PieceMovementRules.is_valid(PieceType.QUEEN, vector)


@pytest.mark.parametrize("vector", [
    Vector4D(),
    Vector4D(3, 2, 0, 0),
    Vector4D(1, 1, 2, 0),
])
def test_queen_rejects_zero_or_unequal_geometry(vector):
    assert not PieceMovementRules.is_valid(PieceType.QUEEN, vector)


@pytest.mark.parametrize("vector", [
    Vector4D(1, 0, 0, 0),
    Vector4D(1, -1, 0, 0),
    Vector4D(0, 0, -1, 1),
    Vector4D(1, 1, -1, 1),
])
def test_king_accepts_one_step_on_any_axes(vector):
    assert PieceMovementRules.is_valid(PieceType.KING, vector)


@pytest.mark.parametrize("vector", [
    Vector4D(),
    Vector4D(2, 0, 0, 0),
    Vector4D(1, 1, -2, 0),
])
def test_king_rejects_zero_or_long_moves(vector):
    assert not PieceMovementRules.is_valid(PieceType.KING, vector)


@pytest.mark.parametrize("vector", [
    Vector4D(2, 1, 0, 0),
    Vector4D(2, 0, -1, 0),
    Vector4D(0, -1, 0, 2),
    Vector4D(0, 0, -2, 1),
])
def test_knight_accepts_l_shape_on_any_two_axes(vector):
    assert PieceMovementRules.is_valid(PieceType.KNIGHT, vector)


@pytest.mark.parametrize("vector", [
    Vector4D(1, 1, 0, 0),
    Vector4D(3, 1, 0, 0),
    Vector4D(2, 1, 1, 0),
    Vector4D(),
])
def test_knight_rejects_non_l_geometry(vector):
    assert not PieceMovementRules.is_valid(PieceType.KNIGHT, vector)


def test_pawn_is_explicitly_deferred():
    assert not PieceMovementRules.supports(PieceType.PAWN)
    with pytest.raises(NotImplementedError):
        PieceMovementRules.is_valid(PieceType.PAWN, Vector4D(0, 1, 0, 0))


def test_slider_classification():
    assert PieceMovementRules.is_slider(PieceType.ROOK)
    assert PieceMovementRules.is_slider(PieceType.BISHOP)
    assert PieceMovementRules.is_slider(PieceType.QUEEN)
    assert not PieceMovementRules.is_slider(PieceType.KING)
    assert not PieceMovementRules.is_slider(PieceType.KNIGHT)
