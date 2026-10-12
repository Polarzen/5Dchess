"""Action-level bounded alpha-beta AI (medium difficulty)."""
from __future__ import annotations

from copy import deepcopy
import time

from src.ai.action_planner import (
    AIActionPlan,
    ActionPlanner,
    ActionPlanningError,
    ActionSearchBudget,
    ActionSearchResult,
    _PRODUCTION_HYBRID_BUDGET,
    apply_action_plan,
    engine_state_signature,
)
from src.ai.base import AIPlayer
from src.ai.evaluator import Evaluator
from src.engine.move_generator import Move
from src.engine.move_validator import MoveValidator
from src.utils.constants import AIDifficulty, ChessColor, GameState


def _medium_budget(
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
        max_states=512,
        max_actions=16,
        max_move_depth=32,
        max_seconds=1.0,
    )
    return ActionSearchBudget(
        max_states=defaults.max_states if max_states is None else max_states,
        max_actions=defaults.max_actions if max_actions is None else max_actions,
        max_move_depth=(
            defaults.max_move_depth if max_move_depth is None else max_move_depth
        ),
        max_seconds=defaults.max_seconds if max_seconds is None else max_seconds,
    )


class AlphaBetaAI(AIPlayer):
    """Bounded minimax over complete submitted Actions.

    A search ply is one complete Action, never an intermediate Move.  The
    root candidate is always retained even when a deeper response search hits
    a budget, so boundedness cannot turn an otherwise valid Action into a
    no-move result.
    """

    def __init__(
        self,
        color: ChessColor,
        search_depth: int = 2,
        budget: ActionSearchBudget | None = None,
        *,
        max_states: int | None = None,
        max_actions: int | None = None,
        max_move_depth: int | None = None,
        max_seconds: float | None = None,
    ):
        if search_depth < 1:
            raise ValueError("search_depth must be at least 1")
        super().__init__(
            color,
            AIDifficulty.MEDIUM,
            _medium_budget(
                budget,
                max_states=max_states,
                max_actions=max_actions,
                max_move_depth=max_move_depth,
                max_seconds=max_seconds,
            ),
        )
        self.search_depth = search_depth
        self.evaluator = Evaluator()
        # Kept as compatibility attributes for callers which inspected the
        # former board-local implementation.
        self.validator = MoveValidator()
        self._timeout = self.budget.max_seconds
        self._start_time = 0.0
        self._nodes_searched = 0
        self._states_used = 0
        self._budget_reason: str | None = None

    def plan_action(self, engine) -> AIActionPlan:
        if engine.current_turn_color != self.color:
            raise ActionPlanningError("wrong_turn", incomplete=False)
        if engine.game_state != GameState.PLAYING:
            raise ActionPlanningError("game_not_playing", incomplete=False)

        self._start_time = time.monotonic()
        self._nodes_searched = 0
        self._states_used = 0
        self._budget_reason = None
        result = self._search_candidates(engine, track_repetition=True)
        if not result.candidates:
            reason = result.termination_reason or "no_legal_action"
            raise ActionPlanningError(
                reason,
                incomplete=result.termination_reason is not None,
                explored_states=result.explored_states,
            )

        counts = result.frontier_repetitions or (0,) * len(result.candidates)
        # Consider progress first if the remaining budget cannot score all
        # candidates. Stable ordering preserves the original order otherwise.
        order = sorted(range(len(result.candidates)), key=lambda index: counts[index] >= 2)
        best_index = order[0]
        best_specs = result.candidates[best_index]
        best_score = float("-inf")
        best_penalty = 0.0
        alpha = float("-inf")
        beta = float("inf")
        completed_root_search = True

        for index in order:
            specs = result.candidates[index]
            if self._deadline_reached():
                completed_root_search = False
                break
            child = self._apply_candidate(engine, specs)
            if child is None:
                continue
            penalty = 0.25 if counts[index] >= 2 else 0.0
            score = self._search_state(
                child,
                self.search_depth - 1,
                alpha + penalty,
                beta,
            ) - penalty
            if score > best_score:
                best_score = score
                best_specs = specs
                best_index = index
                best_penalty = penalty
            alpha = max(alpha, score)

        if best_score == float("-inf"):
            # Preflight guarantees that at least one root candidate is valid,
            # but retain a valid candidate if an external caller changed a
            # clone between enumeration and application.
            best_score = self.evaluator.evaluate_engine(engine, self.color)
            completed_root_search = False

        warning_reason = self._budget_reason
        if result.termination_reason:
            warning_reason = warning_reason or result.termination_reason
        if not completed_root_search:
            warning_reason = warning_reason or "time_budget"
        warning = (
            f"bounded search incomplete: {warning_reason}"
            if warning_reason else None
        )
        return AIActionPlan(
            color=self.color,
            moves=best_specs,
            start_signature=engine_state_signature(engine),
            score=best_score + best_penalty,
            metadata={
                "explored_states": self._states_used,
                "candidate_count": len(result.candidates),
                "search_depth": self.search_depth,
                "search_complete": not bool(warning_reason),
                "selected_index": best_index,
                "repetition_prior_occurrences": counts[best_index],
                "repetition_penalty": best_penalty,
            },
            warning=warning,
        )

    def _deadline_reached(self) -> bool:
        if self._timeout is None:
            return False
        if time.monotonic() - self._start_time >= self._timeout:
            self._budget_reason = self._budget_reason or "time_budget"
            return True
        return False

    def _search_candidates(self, engine, *, track_repetition=False) -> ActionSearchResult:
        """Enumerate with the remaining global state/time budget."""
        if self._deadline_reached():
            return ActionSearchResult((), self._states_used, "time_budget")
        remaining_states = None
        if self.budget.max_states is not None:
            remaining_states = self.budget.max_states - self._states_used
            if remaining_states <= 0:
                self._budget_reason = self._budget_reason or "state_budget"
                return ActionSearchResult((), self._states_used, "state_budget")
        remaining_seconds = None
        if self._timeout is not None:
            remaining_seconds = max(
                0.0,
                self._timeout - (time.monotonic() - self._start_time),
            )
        node_budget = ActionSearchBudget(
            max_states=remaining_states,
            max_actions=self.budget.max_actions,
            max_move_depth=self.budget.max_move_depth,
            max_seconds=remaining_seconds,
        )
        # Remaining time may equal the configured limit on a coarse clock or
        # be slightly smaller on a fine clock. Keep minimax candidate ordering
        # independent of that equality, and share its original absolute deadline
        # so cloning/preparation cannot restart the global wall budget.
        deadline = None if self._timeout is None else self._start_time + self._timeout
        strategy = (
            "probe_then_depth_first" if self.budget == _PRODUCTION_HYBRID_BUDGET
            else "depth_first"
        )
        result = ActionPlanner(
            node_budget, strategy=strategy, deadline=deadline,
            **({"track_repetition": True} if track_repetition else {}),
        ).search(engine)
        self._states_used += result.explored_states
        if result.termination_reason:
            self._budget_reason = self._budget_reason or result.termination_reason
        return result

    def _candidate_plan(self, engine, specs) -> AIActionPlan:
        return AIActionPlan(
            color=engine.current_turn_color,
            moves=specs,
            start_signature=engine_state_signature(engine),
        )

    def _apply_candidate(self, engine, specs):
        child = deepcopy(engine)
        try:
            apply_action_plan(child, self._candidate_plan(child, specs))
        except Exception:
            return None
        return child

    def _search_state(self, engine, depth: int, alpha: float, beta: float) -> float:
        self._nodes_searched += 1
        if depth <= 0 or self._deadline_reached():
            return self.evaluator.evaluate_engine(engine, self.color)

        result = self._search_candidates(engine)
        if not result.candidates:
            if result.termination_reason and result.termination_reason != "game_not_playing":
                return self.evaluator.evaluate_engine(engine, self.color)
            # A completed no-action search is a genuine Action terminal.
            if engine.current_turn_color == self.color:
                return -100000.0
            return 100000.0

        maximizing = engine.current_turn_color == self.color
        best = float("-inf") if maximizing else float("inf")
        searched = False
        for specs in result.candidates:
            if self._deadline_reached():
                break
            child = self._apply_candidate(engine, specs)
            if child is None:
                continue
            searched = True
            score = self._search_state(child, depth - 1, alpha, beta)
            if maximizing:
                best = max(best, score)
                alpha = max(alpha, best)
            else:
                best = min(best, score)
                beta = min(beta, best)
            if alpha >= beta:
                break

        if not searched:
            return self.evaluator.evaluate_engine(engine, self.color)
        return best

    @staticmethod
    def _move_priority(move: Move) -> float:
        """Compatibility ordering helper retained for old integrations."""
        priority = 0.0
        if move.captured:
            priority += move.captured.value - move.piece.value * 0.1
        if move.promotion:
            priority += 9.0
        if move.is_castling:
            priority += 1.0
        if move.is_branching:
            priority += 2.0
        return priority

    @property
    def nodes_searched(self) -> int:
        return self._nodes_searched


__all__ = ["AlphaBetaAI"]
