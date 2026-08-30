"""Easy Action-level AI: choose uniformly from bounded complete Actions."""
from __future__ import annotations

import random
from typing import Any

from src.ai.action_planner import (
    AIActionPlan,
    ActionPlanner,
    ActionPlanningError,
    ActionSearchBudget,
    engine_state_signature,
)
from src.ai.base import AIPlayer
from src.utils.constants import AIDifficulty, ChessColor, GameState


def _budget_from_kwargs(
    budget: ActionSearchBudget | None,
    *,
    max_states: int | None,
    max_actions: int | None,
    max_move_depth: int | None,
    max_seconds: float | None,
) -> ActionSearchBudget:
    if budget is not None:
        return budget
    defaults = ActionSearchBudget()
    return ActionSearchBudget(
        max_states=defaults.max_states if max_states is None else max_states,
        max_actions=defaults.max_actions if max_actions is None else max_actions,
        max_move_depth=(
            defaults.max_move_depth if max_move_depth is None else max_move_depth
        ),
        max_seconds=defaults.max_seconds if max_seconds is None else max_seconds,
    )


class RandomAI(AIPlayer):
    """Easy AI which randomly selects one complete legal Action."""

    def __init__(
        self,
        color: ChessColor,
        rng: random.Random | Any | None = None,
        seed: int | None = None,
        budget: ActionSearchBudget | None = None,
        *,
        random_source: random.Random | Any | None = None,
        max_states: int | None = None,
        max_actions: int | None = None,
        max_move_depth: int | None = None,
        max_seconds: float | None = None,
    ):
        # A budget as the second positional argument is accepted as a small
        # compatibility convenience; injected RNGs remain the normal form.
        if isinstance(rng, ActionSearchBudget) and budget is None:
            budget = rng
            rng = None
        super().__init__(
            color,
            AIDifficulty.EASY,
            _budget_from_kwargs(
                budget,
                max_states=max_states,
                max_actions=max_actions,
                max_move_depth=max_move_depth,
                max_seconds=max_seconds,
            ),
        )
        if random_source is not None:
            if rng is not None:
                raise TypeError("provide only one of rng and random_source")
            rng = random_source
        if rng is None:
            rng = random.Random(seed)
        elif seed is not None:
            raise TypeError("seed cannot be combined with an injected RNG")
        if not hasattr(rng, "choice"):
            raise TypeError("rng must provide choice(sequence)")
        self.rng = rng
        self.random_generator = rng

    def plan_action(self, engine) -> AIActionPlan:
        if engine.current_turn_color != self.color:
            raise ActionPlanningError("wrong_turn", incomplete=False)
        if engine.game_state != GameState.PLAYING:
            raise ActionPlanningError("game_not_playing", incomplete=False)

        result = ActionPlanner(self.budget).search(engine)
        if not result.candidates:
            raise ActionPlanningError(
                result.termination_reason or "no_legal_action",
                incomplete=result.termination_reason is not None,
                explored_states=result.explored_states,
            )

        selected = self.rng.choice(result.candidates)
        selected_index = result.candidates.index(selected)
        warning = None
        if result.termination_reason:
            warning = f"bounded search incomplete: {result.termination_reason}"
        return AIActionPlan(
            color=self.color,
            moves=selected,
            start_signature=engine_state_signature(engine),
            metadata={
                "explored_states": result.explored_states,
                "candidate_count": len(result.candidates),
                "selected_index": selected_index,
                "search_complete": not result.exhausted,
            },
            warning=warning,
        )


__all__ = ["RandomAI"]
