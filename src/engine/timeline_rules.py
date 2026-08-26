"""Rules for active timelines and The Present.

This module owns the turn-level timeline semantics that sit above individual
Move validation/execution.  Timeline storage still uses legacy half-move
``time_point`` keys, so conversion to canonical ``BoardCoord`` is kept at the
boundary here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, TYPE_CHECKING

from src.engine.coordinates import BoardCoord
from src.utils.constants import ChessColor

if TYPE_CHECKING:
    from src.engine.timeline import Timeline


@dataclass(frozen=True, slots=True)
class PresentState:
    """The Present line and the active playable boards touched by it."""

    legacy_time_point: int
    turn: int
    side: ChessColor
    boards: tuple[BoardCoord, ...]

    @property
    def timeline_ids(self) -> tuple[int, ...]:
        return tuple(board.timeline for board in self.boards)


class TimelineRules:
    """Pure multiverse rules for timeline activity and The Present."""

    @staticmethod
    def _owner(timeline: "Timeline") -> ChessColor | None:
        if timeline.timeline_id == 0:
            return None
        if timeline.owner is not None:
            return timeline.owner
        # Compatibility for older/manual timelines.  Signed L already encodes
        # the creator side in the canonical lane model.
        return ChessColor.WHITE if timeline.timeline_id > 0 else ChessColor.BLACK

    @classmethod
    def creator_counts(
        cls,
        timelines: Mapping[int, "Timeline"],
    ) -> dict[ChessColor, int]:
        counts = {ChessColor.WHITE: 0, ChessColor.BLACK: 0}
        for timeline in timelines.values():
            owner = cls._owner(timeline)
            if owner is not None:
                counts[owner] += 1
        return counts

    @classmethod
    def is_active_timeline(
        cls,
        timeline: "Timeline",
        timelines: Mapping[int, "Timeline"],
    ) -> bool:
        """Return whether a timeline participates in The Present.

        The main timeline is always active.  The nth timeline created by one
        player is active when the opponent has created at least n-1 timelines.
        With signed canonical lanes, ``abs(timeline_id)`` is that creation rank.
        """
        if timeline.timeline_id == 0:
            return True

        owner = cls._owner(timeline)
        if owner is None:
            return True
        opponent = owner.opposite()
        opponent_count = cls.creator_counts(timelines)[opponent]
        creation_rank = abs(timeline.timeline_id)
        return opponent_count >= creation_rank - 1

    @classmethod
    def activity_map(
        cls,
        timelines: Mapping[int, "Timeline"],
    ) -> dict[int, bool]:
        return {
            timeline_id: cls.is_active_timeline(timeline, timelines)
            for timeline_id, timeline in timelines.items()
        }

    @classmethod
    def refresh_activity(cls, timelines: Mapping[int, "Timeline"]) -> None:
        """Synchronize the cached ``Timeline.is_active`` compatibility flag."""
        for timeline_id, active in cls.activity_map(timelines).items():
            timelines[timeline_id].is_active = active

    @classmethod
    def present(
        cls,
        timelines: Mapping[int, "Timeline"],
    ) -> PresentState | None:
        """Return The Present: the earliest playable board on active timelines."""
        active = [
            timeline
            for timeline in timelines.values()
            if timeline.positions and cls.is_active_timeline(timeline, timelines)
        ]
        if not active:
            return None

        time_point = min(timeline.latest_time for timeline in active)
        boards: list[BoardCoord] = []
        side: ChessColor | None = None
        for timeline in sorted(active, key=lambda item: item.timeline_id):
            if timeline.latest_time != time_point:
                continue
            position = timeline.positions[time_point]
            coord = BoardCoord.from_legacy_time_point(
                timeline=timeline.timeline_id,
                time_point=time_point,
                side=position.turn,
            )
            if side is None:
                side = coord.side
            elif coord.side != side:
                raise ValueError("boards on the same Present column disagree on side")
            boards.append(coord)

        if side is None:
            return None
        canonical = boards[0]
        return PresentState(
            legacy_time_point=time_point,
            turn=canonical.turn,
            side=side,
            boards=tuple(boards),
        )

    @classmethod
    def required_boards(
        cls,
        timelines: Mapping[int, "Timeline"],
        color: ChessColor,
    ) -> tuple[BoardCoord, ...]:
        """Boards that must be advanced before ``color`` may submit."""
        present = cls.present(timelines)
        if present is None or present.side != color:
            return ()
        return present.boards

    @classmethod
    def movable_boards(
        cls,
        timelines: Mapping[int, "Timeline"],
        color: ChessColor,
    ) -> tuple[BoardCoord, ...]:
        """All playable boards on which ``color`` may optionally make a move.

        Inactive timelines and boards ahead of The Present are optional rather
        than forbidden, so activity is deliberately not used as a filter here.
        """
        boards: list[BoardCoord] = []
        for timeline_id in sorted(timelines):
            timeline = timelines[timeline_id]
            if not timeline.positions:
                continue
            time_point = timeline.latest_time
            position = timeline.positions[time_point]
            if position.turn != color:
                continue
            boards.append(
                BoardCoord.from_legacy_time_point(
                    timeline=timeline_id,
                    time_point=time_point,
                    side=position.turn,
                )
            )
        return tuple(boards)
