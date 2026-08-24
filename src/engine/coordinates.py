"""Core coordinate primitives for 5D Chess.

The rules engine treats a square as a spatial coordinate (x, y) attached to a
specific board coordinate (timeline, turn, side).  Movement geometry is then
expressed as a four-dimensional vector (dx, dy, dt, dl).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from math import gcd

from src.utils.constants import BOARD_SIZE, ChessColor


@dataclass(frozen=True, slots=True, order=True)
class BoardCoord:
    """Identity of one board in the multiverse.

    ``turn`` is the canonical full-turn coordinate. ``side`` identifies the
    half-move board for that turn. During the migration from the legacy
    ``Position.time_point`` model, callers may temporarily map ``time_point``
    into ``turn`` without changing the old state-transition code.
    """

    timeline: int
    turn: int
    side: ChessColor

    def __post_init__(self) -> None:
        if self.turn < 0:
            raise ValueError("turn must be non-negative")

    def next(self) -> "BoardCoord":
        """Return the board coordinate after one local move on this timeline."""
        if self.side == ChessColor.WHITE:
            return BoardCoord(self.timeline, self.turn, ChessColor.BLACK)
        return BoardCoord(self.timeline, self.turn + 1, ChessColor.WHITE)

    def __str__(self) -> str:
        suffix = "w" if self.side == ChessColor.WHITE else "b"
        return f"L{self.timeline}:T{self.turn}{suffix}"


@dataclass(frozen=True, slots=True)
class Square5D:
    """A spatial square on a specific multiverse board."""

    board: BoardCoord
    x: int
    y: int

    def __post_init__(self) -> None:
        if not (0 <= self.x < BOARD_SIZE and 0 <= self.y < BOARD_SIZE):
            raise ValueError(f"square out of bounds: ({self.x}, {self.y})")

    @property
    def timeline(self) -> int:
        return self.board.timeline

    @property
    def turn(self) -> int:
        return self.board.turn

    @property
    def side(self) -> ChessColor:
        return self.board.side

    def vector_to(self, other: "Square5D") -> "Vector4D":
        return Vector4D.between(self, other)


@dataclass(frozen=True, slots=True)
class Vector4D:
    """Movement vector across space, time and timelines.

    Component order is ``(dx, dy, dt, dl)``.  Board ``side`` is deliberately
    not encoded as a fifth movement axis; geometric moves compare boards with
    the same side-to-move phase.
    """

    dx: int = 0
    dy: int = 0
    dt: int = 0
    dl: int = 0

    @classmethod
    def between(cls, source: Square5D, destination: Square5D) -> "Vector4D":
        if source.side != destination.side:
            raise ValueError("cannot build a 4D move vector across different board sides")
        return cls(
            dx=destination.x - source.x,
            dy=destination.y - source.y,
            dt=destination.turn - source.turn,
            dl=destination.timeline - source.timeline,
        )

    @property
    def components(self) -> tuple[int, int, int, int]:
        return self.dx, self.dy, self.dt, self.dl

    @property
    def nonzero_components(self) -> tuple[int, ...]:
        return tuple(value for value in self.components if value != 0)

    @property
    def dimensions(self) -> int:
        """Number of axes participating in the move."""
        return len(self.nonzero_components)

    @property
    def magnitudes(self) -> tuple[int, ...]:
        return tuple(abs(value) for value in self.nonzero_components)

    @property
    def is_zero(self) -> bool:
        return self.dimensions == 0

    @property
    def equal_magnitude(self) -> bool:
        """Whether all participating axes move the same distance."""
        magnitudes = self.magnitudes
        return bool(magnitudes) and len(set(magnitudes)) == 1

    def primitive(self) -> "Vector4D":
        """Reduce the vector to its smallest integer step."""
        values = self.magnitudes
        if not values:
            return self
        divisor = reduce(gcd, values)
        return Vector4D(
            self.dx // divisor,
            self.dy // divisor,
            self.dt // divisor,
            self.dl // divisor,
        )
