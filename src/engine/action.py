"""Action / moveset model for one player's 5D turn.

A 5D turn is not a single Move.  An Action is the sequence of Moves performed
by one player until The Present has shifted to the opponent and submission is
therefore legal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, TYPE_CHECKING

from src.engine.move_generator import Move
from src.engine.timeline_rules import PresentState, TimelineRules
from src.utils.constants import ChessColor

if TYPE_CHECKING:
    from src.engine.timeline import Timeline


@dataclass(slots=True)
class Action:
    """Moves accumulated during one player's sub-turn."""

    color: ChessColor
    starting_present: PresentState | None
    moves: list[Move] = field(default_factory=list)
    submitted: bool = False

    def record(self, move: Move) -> None:
        if self.submitted:
            raise ValueError("cannot append a move to a submitted action")
        if move.piece.color != self.color:
            raise ValueError("action cannot contain the opponent's move")
        self.moves.append(move)


class ActionRules:
    """Pure rules governing a player's multi-Move Action."""

    @staticmethod
    def begin(
        color: ChessColor,
        timelines: Mapping[int, "Timeline"],
    ) -> Action:
        return Action(
            color=color,
            starting_present=TimelineRules.present(timelines),
        )

    @staticmethod
    def required_boards(
        action: Action,
        timelines: Mapping[int, "Timeline"],
    ):
        return TimelineRules.required_boards(timelines, action.color)

    @staticmethod
    def movable_boards(
        action: Action,
        timelines: Mapping[int, "Timeline"],
    ):
        return TimelineRules.movable_boards(timelines, action.color)

    @classmethod
    def can_play_move(
        cls,
        action: Action,
        move: Move,
        timelines: Mapping[int, "Timeline"],
    ) -> bool:
        if action.submitted:
            return False
        if move.piece.color != action.color:
            return False
        if move.source.side != action.color:
            return False
        return move.source.board in cls.movable_boards(action, timelines)

    @staticmethod
    def can_submit(
        action: Action,
        timelines: Mapping[int, "Timeline"],
    ) -> bool:
        """Submission requires both Present progress and multiverse royal safety."""
        if action.submitted:
            return False
        present = TimelineRules.present(timelines)
        if present is None or present.side == action.color:
            return False

        # Lazy import keeps Action's data model independent while making the
        # final submission boundary the owner of royal-safety enforcement.
        from src.engine.royal_rules import RoyalRules

        return RoyalRules(timelines).is_action_safe(action.color)

    @classmethod
    def submit(
        cls,
        action: Action,
        timelines: Mapping[int, "Timeline"],
    ) -> bool:
        if not cls.can_submit(action, timelines):
            return False
        action.submitted = True
        return True
