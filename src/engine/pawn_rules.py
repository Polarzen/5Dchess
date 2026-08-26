"""Color-relative 5D pawn movement rules.

Pawns are intentionally separate from ``PieceMovementRules`` because their
geometry depends on color, capture state and whether the pawn has moved before.
The standard pawn uses two paired planes only:

- spatial plane: X/Y
- temporal plane: T/L

It may not mix one spatial and one temporal axis when capturing.
"""
from __future__ import annotations

from src.engine.coordinates import Vector4D
from src.utils.constants import ChessColor, PieceType


class PawnRules:
    """Pure geometry and special-rule predicates for the standard 5D pawn."""

    @staticmethod
    def spatial_forward(color: ChessColor) -> int:
        """Return the forward Y direction in the repository's board layout."""
        return -1 if color == ChessColor.WHITE else 1

    @staticmethod
    def timeline_forward(color: ChessColor) -> int:
        """Return the forward L direction, toward the opponent's branch side."""
        # White-created branches use +L and Black-created branches use -L.
        # A pawn advances toward the opponent's branch direction.
        return -1 if color == ChessColor.WHITE else 1

    @staticmethod
    def promotion_rank(color: ChessColor) -> int:
        return 0 if color == ChessColor.WHITE else 7

    @classmethod
    def reaches_promotion_rank(cls, color: ChessColor, y: int) -> bool:
        return y == cls.promotion_rank(color)

    @staticmethod
    def is_valid_promotion(piece_type: PieceType | None) -> bool:
        """The standard Steam rules promote pawns to Queen only."""
        return piece_type == PieceType.QUEEN

    @classmethod
    def is_valid_vector(
        cls,
        color: ChessColor,
        vector: Vector4D,
        *,
        capture: bool,
        unmoved: bool,
    ) -> bool:
        """Return whether a pawn vector is legal before occupancy/path checks."""
        if vector.is_zero:
            return False

        spatial_forward = cls.spatial_forward(color)
        timeline_forward = cls.timeline_forward(color)

        if capture:
            # Standard board capture: one X sideways + one Y forward.
            spatial_capture = (
                abs(vector.dx) == 1
                and vector.dy == spatial_forward
                and vector.dt == 0
                and vector.dl == 0
            )
            # Temporal capture: one T sideways + one L forward.
            temporal_capture = (
                vector.dx == 0
                and vector.dy == 0
                and abs(vector.dt) == 1
                and vector.dl == timeline_forward
            )
            return spatial_capture or temporal_capture

        # Non-capturing advances use exactly one forward axis.
        one_spatial = (
            vector.dx == 0
            and vector.dy == spatial_forward
            and vector.dt == 0
            and vector.dl == 0
        )
        one_timeline = (
            vector.dx == 0
            and vector.dy == 0
            and vector.dt == 0
            and vector.dl == timeline_forward
        )
        if one_spatial or one_timeline:
            return True

        if not unmoved:
            return False

        two_spatial = (
            vector.dx == 0
            and vector.dy == 2 * spatial_forward
            and vector.dt == 0
            and vector.dl == 0
        )
        two_timeline = (
            vector.dx == 0
            and vector.dy == 0
            and vector.dt == 0
            and vector.dl == 2 * timeline_forward
        )
        return two_spatial or two_timeline

    @staticmethod
    def is_double_advance(vector: Vector4D) -> bool:
        return (
            vector.dx == 0
            and vector.dt == 0
            and (
                (abs(vector.dy) == 2 and vector.dl == 0)
                or (vector.dy == 0 and abs(vector.dl) == 2)
            )
        )

    @staticmethod
    def is_spatial_double(vector: Vector4D) -> bool:
        return (
            vector.dx == 0
            and abs(vector.dy) == 2
            and vector.dt == 0
            and vector.dl == 0
        )

    @staticmethod
    def is_timeline_double(vector: Vector4D) -> bool:
        return (
            vector.dx == 0
            and vector.dy == 0
            and vector.dt == 0
            and abs(vector.dl) == 2
        )
