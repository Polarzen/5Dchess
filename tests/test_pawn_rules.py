from src.engine import PawnRules, Vector4D
from src.utils.constants import ChessColor, PieceType


def test_forward_directions_are_color_relative():
    assert PawnRules.spatial_forward(ChessColor.WHITE) == -1
    assert PawnRules.spatial_forward(ChessColor.BLACK) == 1
    assert PawnRules.timeline_forward(ChessColor.WHITE) == -1
    assert PawnRules.timeline_forward(ChessColor.BLACK) == 1


def test_white_pawn_advances_in_y_or_l_only():
    assert PawnRules.is_valid_vector(
        ChessColor.WHITE, Vector4D(0, -1, 0, 0), capture=False, unmoved=False
    )
    assert PawnRules.is_valid_vector(
        ChessColor.WHITE, Vector4D(0, 0, 0, -1), capture=False, unmoved=False
    )
    assert not PawnRules.is_valid_vector(
        ChessColor.WHITE, Vector4D(0, 0, -1, 0), capture=False, unmoved=False
    )


def test_black_pawn_advances_in_opposite_y_and_l_directions():
    assert PawnRules.is_valid_vector(
        ChessColor.BLACK, Vector4D(0, 1, 0, 0), capture=False, unmoved=False
    )
    assert PawnRules.is_valid_vector(
        ChessColor.BLACK, Vector4D(0, 0, 0, 1), capture=False, unmoved=False
    )
    assert not PawnRules.is_valid_vector(
        ChessColor.BLACK, Vector4D(0, 0, 0, -1), capture=False, unmoved=False
    )


def test_first_move_may_double_in_y_or_l_only():
    white_y = Vector4D(0, -2, 0, 0)
    white_l = Vector4D(0, 0, 0, -2)

    assert PawnRules.is_valid_vector(
        ChessColor.WHITE, white_y, capture=False, unmoved=True
    )
    assert PawnRules.is_valid_vector(
        ChessColor.WHITE, white_l, capture=False, unmoved=True
    )
    assert not PawnRules.is_valid_vector(
        ChessColor.WHITE, white_y, capture=False, unmoved=False
    )
    assert not PawnRules.is_valid_vector(
        ChessColor.WHITE, white_l, capture=False, unmoved=False
    )


def test_capture_is_confined_to_xy_or_tl_plane():
    assert PawnRules.is_valid_vector(
        ChessColor.WHITE, Vector4D(1, -1, 0, 0), capture=True, unmoved=False
    )
    assert PawnRules.is_valid_vector(
        ChessColor.WHITE, Vector4D(0, 0, 1, -1), capture=True, unmoved=False
    )
    assert PawnRules.is_valid_vector(
        ChessColor.WHITE, Vector4D(0, 0, -1, -1), capture=True, unmoved=False
    )

    # No mixed spatial/temporal diagonals for the standard pawn.
    assert not PawnRules.is_valid_vector(
        ChessColor.WHITE, Vector4D(1, 0, 0, -1), capture=True, unmoved=False
    )
    assert not PawnRules.is_valid_vector(
        ChessColor.WHITE, Vector4D(0, -1, 1, 0), capture=True, unmoved=False
    )


def test_promotion_is_queen_only():
    assert PawnRules.is_valid_promotion(PieceType.QUEEN)
    assert not PawnRules.is_valid_promotion(PieceType.ROOK)
    assert not PawnRules.is_valid_promotion(PieceType.BISHOP)
    assert not PawnRules.is_valid_promotion(PieceType.KNIGHT)
    assert not PawnRules.is_valid_promotion(None)
