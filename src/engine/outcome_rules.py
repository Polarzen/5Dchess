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
from src.utils.logger import logger

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
        """Return terminal outcome for ``color``, or ``None`` if play continues.

        A bounded Action search may stop before proving whether a legal Action
        exists.  Such an exhausted result is deliberately treated as unknown,
        not as checkmate/stalemate.  A transient warning is attached to the
        engine and emitted to the logger so production runs never fail silently.
        """
        if color is None:
            color = engine.current_turn_color

        # The warning is transient diagnostic state; every fresh evaluation
        # clears an older warning before running the new search.
        setattr(engine, "rule_warning", None)

        search_result = ActionSearch().find_legal_action(engine, color)
        if search_result.has_legal_action:
            return None

        if search_result.exhausted:
            warning = (
                "Action 合法性搜索达到安全上限 "
                f"({search_result.termination_reason}, "
                f"explored={search_result.explored_states})；"
                "为避免误判将杀/逼和，当前结果保持未决。"
            )
            setattr(engine, "rule_warning", warning)
            logger.warning(warning)
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
