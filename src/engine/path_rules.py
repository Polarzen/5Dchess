"""4D path tracing and obstruction rules for sliding pieces.

The path layer is intentionally independent from timeline mutation and move
execution. It can trace the intermediate 5D squares between two canonical
coordinates and ask a caller-provided board resolver whether those squares are
traversable.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from src.engine.coordinates import BoardCoord, Square5D
from src.engine.piece_movement import PieceMovementRules
from src.utils.constants import PieceType


class BoardOccupancy(Protocol):
    """Minimal board interface required by path obstruction checks."""

    def get_piece(self, x: int, y: int):
        ...


BoardResolver = Callable[[BoardCoord], BoardOccupancy | None]


class PathBlockReason(str, Enum):
    """Why a sliding path cannot be traversed."""

    MISSING_BOARD = "missing_board"
    OCCUPIED = "occupied"


@dataclass(frozen=True, slots=True)
class PathBlocker:
    """First obstruction encountered while tracing a path."""

    square: Square5D
    reason: PathBlockReason


class PathRules:
    """Pure 4D path tracing for rook, bishop and queen movement."""

    @classmethod
    def intermediate_squares(
        cls,
        piece_type: PieceType,
        source: Square5D,
        destination: Square5D,
    ) -> tuple[Square5D, ...]:
        """Return all squares strictly between source and destination.

        The move must already have valid slider geometry. Source and destination
        are excluded from the result because occupancy of those endpoints is
        handled by move-generation / capture rules, not path blocking.
        """
        if not PieceMovementRules.is_slider(piece_type):
            raise ValueError(f"{piece_type.name} is not a sliding piece")

        vector = source.vector_to(destination)
        if not PieceMovementRules.is_valid(piece_type, vector):
            raise ValueError(
                f"invalid {piece_type.name} movement geometry for path: {vector}"
            )

        distance = max(vector.magnitudes)
        if distance <= 1:
            return ()

        step = vector.primitive()
        squares: list[Square5D] = []
        for index in range(1, distance):
            board = BoardCoord(
                timeline=source.timeline + step.dl * index,
                turn=source.turn + step.dt * index,
                side=source.side,
            )
            squares.append(Square5D(
                board=board,
                x=source.x + step.dx * index,
                y=source.y + step.dy * index,
            ))

        return tuple(squares)

    @classmethod
    def first_blocker(
        cls,
        piece_type: PieceType,
        source: Square5D,
        destination: Square5D,
        resolve_board: BoardResolver,
    ) -> PathBlocker | None:
        """Return the first missing-board or occupied-square obstruction."""
        for square in cls.intermediate_squares(piece_type, source, destination):
            board = resolve_board(square.board)
            if board is None:
                return PathBlocker(square, PathBlockReason.MISSING_BOARD)
            if board.get_piece(square.x, square.y) is not None:
                return PathBlocker(square, PathBlockReason.OCCUPIED)
        return None

    @classmethod
    def is_clear(
        cls,
        piece_type: PieceType,
        source: Square5D,
        destination: Square5D,
        resolve_board: BoardResolver,
    ) -> bool:
        """Return whether every intermediate 4D square exists and is empty."""
        return cls.first_blocker(
            piece_type,
            source,
            destination,
            resolve_board,
        ) is None
