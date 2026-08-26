"""5D Checkmate / Stalemate classification.

A terminal position is defined globally, not board-by-board.  The current player
must have no complete legal Action.  If a forced pass over all active Present
boards would expose a royal King, the result is checkmate; otherwise it is
stalemate.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from src.engine.action_search import ActionSearch, ActionSearchResult
from src.engine.royal_rules import RoyalRules
from src.utils.constants import ChessColor

if TYPE_CHECKING:
    from src.engine.engine import FiveDEngine


class OutcomeKind(str, Enum):
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"


@dataclass(frozen=True, slots=True)
class MultiverseOutcome:
    """Terminal result for the player whose Action is due."""

    kind: OutcomeKind
    loser: ChessColor | None
    winner: ChessColor | None
    in_check: bool
    explored_states: int


class OutcomeRules:
    """Global terminal-state rules above ActionSearch and RoyalRules."""

    @classmethod
    def evaluate(
        cls,
        engine: "FiveDEngine",
        color: ChessColor | None = None,
    ) -> MultiverseOutcome | None:
        """Return terminal outcome for ``color``, or ``None`` if play continues."""
        if color is None:
            color = engine.current_turn_color

        search_result = ActionSearch().find_legal_action(engine, color)
        if search_result.has_legal_action:
            return None

        in_check = RoyalRules(
            engine.timeline_manager.timelines
        ).is_in_check(color)

        if in_check:
            return MultiverseOutcome(
                kind=OutcomeKind.CHECKMATE,
                loser=color,
                winner=color.opposite(),
                in_check=True,
                explored_states=search_result.explored_states,
            )

        return MultiverseOutcome(
            kind=OutcomeKind.STALEMATE,
            loser=None,
            winner=None,
            in_check=False,
            explored_states=search_result.explored_states,
        )

    @staticmethod
    def has_legal_action(
        engine: "FiveDEngine",
        color: ChessColor | None = None,
    ) -> ActionSearchResult:
        """Expose the complete Action search for callers/tests/analysis."""
        return ActionSearch().find_legal_action(engine, color)
