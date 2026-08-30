"""Hard Action-level AI with a larger bounded action search."""
from __future__ import annotations

from src.ai.action_planner import ActionSearchBudget
from src.ai.alpha_beta import AlphaBetaAI
from src.ai.opening_book import OpeningBook
from src.utils.constants import AIDifficulty, ChessColor


def _hard_budget(
    budget: ActionSearchBudget | None,
    *,
    max_states: int | None,
    max_actions: int | None,
    max_move_depth: int | None,
    max_seconds: float | None,
) -> ActionSearchBudget:
    if budget is not None:
        return budget
    defaults = ActionSearchBudget(
        max_states=1536,
        max_actions=12,
        max_move_depth=32,
        max_seconds=2.0,
    )
    return ActionSearchBudget(
        max_states=defaults.max_states if max_states is None else max_states,
        max_actions=defaults.max_actions if max_actions is None else max_actions,
        max_move_depth=(
            defaults.max_move_depth if max_move_depth is None else max_move_depth
        ),
        max_seconds=defaults.max_seconds if max_seconds is None else max_seconds,
    )


class HardAI(AlphaBetaAI):
    """Hard AI: bounded negamax/minimax over complete Actions.

    The opening book remains available as a legacy attribute for integrations
    that display it, but canonical planning never consults it.
    """

    def __init__(
        self,
        color: ChessColor,
        search_depth: int = 4,
        budget: ActionSearchBudget | None = None,
        *,
        max_states: int | None = None,
        max_actions: int | None = None,
        max_move_depth: int | None = None,
        max_seconds: float | None = None,
    ):
        super().__init__(
            color,
            search_depth=search_depth,
            budget=_hard_budget(
                budget,
                max_states=max_states,
                max_actions=max_actions,
                max_move_depth=max_move_depth,
                max_seconds=max_seconds,
            ),
        )
        self.difficulty = AIDifficulty.HARD
        self.opening_book = OpeningBook()
        # Old callers sometimes reached through ``hard.alpha_beta``.  The
        # canonical implementation is this Action-level search object itself.
        self.alpha_beta = self


__all__ = ["HardAI"]
