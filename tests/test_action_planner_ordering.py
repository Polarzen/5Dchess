"""Regression coverage for deterministic ActionPlanner move ordering."""

from src.ai.action_planner import _move_sort_key
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.move_generator import Move
from src.engine.piece import Piece
from src.utils.constants import ChessColor, PieceType


def _square(timeline: int, x: int, y: int) -> Square5D:
    return Square5D(BoardCoord(timeline, 0, ChessColor.WHITE), x, y)


def test_non_branching_moves_sort_before_branching_moves_without_filtering():
    piece = Piece(PieceType.ROOK, ChessColor.WHITE)
    branching = Move(
        piece=piece,
        source=_square(-1, 0, 0),
        destination=_square(-2, 0, 1),
        is_branching=True,
        created_timeline=-3,
    )
    ordinary = Move(
        piece=piece,
        source=_square(1, 7, 7),
        destination=_square(1, 7, 6),
    )

    # The branching move has the lexicographically earlier source coordinate,
    # so the historical coordinate-first key would place it first.  Planner
    # ordering must instead prefer a non-branching witness while retaining both.
    ordered = sorted((branching, ordinary), key=_move_sort_key)

    assert ordered == [ordinary, branching]
    assert branching in ordered
    assert ordinary in ordered
