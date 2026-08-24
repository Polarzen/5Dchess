"""Piece-specific 4D movement geometry for 5D Chess.

This module answers only one question: whether a movement vector has a legal
shape for a piece. It deliberately does not inspect board occupancy, path
blocking, timeline activity, branching, check, or action-level legality.
"""
from __future__ import annotations

from src.engine.coordinates import Vector4D
from src.utils.constants import PieceType


class PieceMovementRules:
    """Pure geometric movement predicates for non-pawn pieces."""

    _SUPPORTED = frozenset({
        PieceType.ROOK,
        PieceType.BISHOP,
        PieceType.QUEEN,
        PieceType.KING,
        PieceType.KNIGHT,
    })

    _SLIDERS = frozenset({
        PieceType.ROOK,
        PieceType.BISHOP,
        PieceType.QUEEN,
    })

    @classmethod
    def supports(cls, piece_type: PieceType) -> bool:
        """Return whether this rules layer currently implements the piece."""
        return piece_type in cls._SUPPORTED

    @classmethod
    def is_slider(cls, piece_type: PieceType) -> bool:
        """Return whether the piece travels through intermediate 4D squares."""
        return piece_type in cls._SLIDERS

    @classmethod
    def is_valid(cls, piece_type: PieceType, vector: Vector4D) -> bool:
        """Return whether *vector* has a legal geometric shape for *piece_type*.

        Pawn geometry is intentionally deferred because its legal vectors depend
        on color-relative forward axes, captures, first-move state and promotion.
        """
        if piece_type == PieceType.PAWN:
            raise NotImplementedError("pawn movement geometry is handled separately")

        if piece_type not in cls._SUPPORTED:
            raise ValueError(f"unsupported piece type: {piece_type!r}")

        if vector.is_zero:
            return False

        if piece_type == PieceType.ROOK:
            return cls._rook(vector)
        if piece_type == PieceType.BISHOP:
            return cls._bishop(vector)
        if piece_type == PieceType.QUEEN:
            return cls._queen(vector)
        if piece_type == PieceType.KING:
            return cls._king(vector)
        if piece_type == PieceType.KNIGHT:
            return cls._knight(vector)

        return False

    @staticmethod
    def _rook(vector: Vector4D) -> bool:
        # One axis, arbitrary non-zero distance.
        return vector.dimensions == 1

    @staticmethod
    def _bishop(vector: Vector4D) -> bool:
        # Exactly two axes, equal distance on both.
        return vector.dimensions == 2 and vector.equal_magnitude

    @staticmethod
    def _queen(vector: Vector4D) -> bool:
        # Any 1-4 axes, with the same distance on every participating axis.
        return 1 <= vector.dimensions <= 4 and vector.equal_magnitude

    @staticmethod
    def _king(vector: Vector4D) -> bool:
        # Queen-like directions, exactly one step along every participating axis.
        return 1 <= vector.dimensions <= 4 and all(
            magnitude == 1 for magnitude in vector.magnitudes
        )

    @staticmethod
    def _knight(vector: Vector4D) -> bool:
        # L-shape across any pair of the four axes.
        return (
            vector.dimensions == 2
            and sorted(vector.magnitudes) == [1, 2]
        )
