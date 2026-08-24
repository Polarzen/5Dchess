"""Canonical read-only view over the legacy timeline storage.

Timeline.positions is still keyed by the old half-move ``time_point`` integer.
The rest of the 4D rules should not need to know that representation. This
adapter resolves canonical ``BoardCoord`` objects and centralizes historical /
playable-board classification until Timeline itself is migrated.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, TYPE_CHECKING

from src.engine.board import Position
from src.engine.coordinates import BoardCoord
from src.utils.constants import ChessColor

if TYPE_CHECKING:
    from src.engine.timeline import Timeline


class BoardRole(str, Enum):
    """Role of an existing board inside its timeline."""

    HISTORICAL = "historical"
    PLAYABLE = "playable"


@dataclass(frozen=True, slots=True)
class ResolvedBoard:
    """Canonical metadata paired with the underlying legacy Position."""

    coord: BoardCoord
    position: Position
    role: BoardRole
    timeline_active: bool

    @property
    def is_playable(self) -> bool:
        return self.role == BoardRole.PLAYABLE

    @property
    def is_historical(self) -> bool:
        return self.role == BoardRole.HISTORICAL


class MultiverseBoardView:
    """Read-only canonical lookup layer for a set of legacy timelines."""

    def __init__(self, timelines: Mapping[int, "Timeline"] | None = None):
        self.timelines = timelines or {}

    def resolve(self, coord: BoardCoord) -> Position | None:
        """Resolve a canonical board coordinate to its stored Position.

        Missing timelines / time points return ``None``. If a stored Position
        contradicts its dictionary key, timeline id, or canonical side phase,
        ``ValueError`` is raised because that is corrupted state, not a missing
        board.
        """
        timeline = self.timelines.get(coord.timeline)
        if timeline is None:
            return None

        time_point = coord.legacy_time_point
        position = timeline.positions.get(time_point)
        if position is None:
            return None

        self._validate_stored_position(coord.timeline, time_point, position)
        if position.turn != coord.side:
            return None
        return position

    def describe(self, coord: BoardCoord) -> ResolvedBoard | None:
        """Resolve a board and classify it as historical or playable."""
        position = self.resolve(coord)
        if position is None:
            return None

        timeline = self.timelines[coord.timeline]
        role = (
            BoardRole.PLAYABLE
            if coord.legacy_time_point == timeline.latest_time
            else BoardRole.HISTORICAL
        )
        return ResolvedBoard(
            coord=coord,
            position=position,
            role=role,
            timeline_active=timeline.is_active,
        )

    def is_playable(self, coord: BoardCoord) -> bool:
        resolved = self.describe(coord)
        return bool(resolved and resolved.is_playable)

    def is_historical(self, coord: BoardCoord) -> bool:
        resolved = self.describe(coord)
        return bool(resolved and resolved.is_historical)

    def latest_coord(self, timeline_id: int) -> BoardCoord | None:
        """Return the canonical coordinate of a timeline's latest board."""
        timeline = self.timelines.get(timeline_id)
        if timeline is None or not timeline.positions:
            return None
        time_point = timeline.latest_time
        position = timeline.positions[time_point]
        self._validate_stored_position(timeline_id, time_point, position)
        return BoardCoord.from_legacy_time_point(
            timeline=timeline_id,
            time_point=time_point,
            side=position.turn,
        )

    def iter_boards(
        self,
        *,
        side: ChessColor | None = None,
        active_only: bool = False,
        playable_only: bool = False,
    ) -> Iterable[ResolvedBoard]:
        """Iterate existing boards in deterministic canonical order."""
        for timeline_id in sorted(self.timelines):
            timeline = self.timelines[timeline_id]
            if active_only and not timeline.is_active:
                continue

            for time_point in sorted(timeline.positions):
                position = timeline.positions[time_point]
                self._validate_stored_position(timeline_id, time_point, position)
                if side is not None and position.turn != side:
                    continue

                coord = BoardCoord.from_legacy_time_point(
                    timeline=timeline_id,
                    time_point=time_point,
                    side=position.turn,
                )
                role = (
                    BoardRole.PLAYABLE
                    if time_point == timeline.latest_time
                    else BoardRole.HISTORICAL
                )
                if playable_only and role != BoardRole.PLAYABLE:
                    continue

                yield ResolvedBoard(
                    coord=coord,
                    position=position,
                    role=role,
                    timeline_active=timeline.is_active,
                )

    @staticmethod
    def _validate_stored_position(
        timeline_id: int,
        time_point: int,
        position: Position,
    ) -> None:
        if position.timeline_id != timeline_id:
            raise ValueError(
                f"timeline {timeline_id} stores position for timeline "
                f"{position.timeline_id}"
            )
        if position.time_point != time_point:
            raise ValueError(
                f"timeline key {time_point} stores position time "
                f"{position.time_point}"
            )
        BoardCoord.from_legacy_time_point(
            timeline=timeline_id,
            time_point=time_point,
            side=position.turn,
        )
