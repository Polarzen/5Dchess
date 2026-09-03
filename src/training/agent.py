"""Inference wrapper that scores only canonical ActionPlanner candidates."""
from __future__ import annotations

import time
from dataclasses import dataclass

import torch

from src.ai.action_planner import (
    AIActionPlan,
    ActionPlanner,
    ActionPlanningError,
    ActionSearchBudget,
    engine_state_signature,
)
from src.training.encoding import encode_candidates, encode_state
from src.utils.constants import ChessColor, GameState


@dataclass(frozen=True, slots=True)
class NeuralDecision:
    selected_index: int
    logits: tuple[float, ...]
    value: float
    inference_ms: float
    explored_states: int
    termination_reason: str | None


class NeuralPolicyValueAgent:
    """Use a PolicyValueModel as a scorer inside the canonical legal Action set."""

    def __init__(
        self,
        model,
        color: ChessColor,
        *,
        device="cpu",
        budget: ActionSearchBudget | None = None,
    ) -> None:
        self.model = model
        self.color = color
        self.device = torch.device(device)
        self.budget = budget or ActionSearchBudget()
        self.last_decision: NeuralDecision | None = None
        self.model.to(self.device)

    def _tensor(self, array, *, add_batch: bool = True):
        tensor = torch.as_tensor(array, device=self.device)
        if add_batch:
            tensor = tensor.unsqueeze(0)
        return tensor

    def score_candidates(self, engine):
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
        state = encode_state(engine, self.color, self.model.encoding_config)
        actions = encode_candidates(engine, result.candidates, self.model.encoding_config)
        started = time.perf_counter()
        self.model.eval()
        with torch.inference_mode():
            logits, value = self.model(
                self._tensor(state.boards).float(),
                self._tensor(state.board_meta).float(),
                self._tensor(state.board_mask).bool(),
                self._tensor(state.global_features).float(),
                self._tensor(actions.moves).float(),
                self._tensor(actions.move_mask).bool(),
                self._tensor(actions.action_global).float(),
                self._tensor(actions.candidate_mask).bool(),
            )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        selected = int(logits[0].argmax().item())
        decision = NeuralDecision(
            selected_index=selected,
            logits=tuple(float(value_) for value_ in logits[0].detach().cpu().tolist()),
            value=float(value[0].detach().cpu().item()),
            inference_ms=elapsed_ms,
            explored_states=result.explored_states,
            termination_reason=result.termination_reason,
        )
        self.last_decision = decision
        return result, decision

    def plan_action(self, engine) -> AIActionPlan:
        result, decision = self.score_candidates(engine)
        warning = None
        if result.termination_reason:
            warning = f"bounded candidate search incomplete: {result.termination_reason}"
        return AIActionPlan(
            color=self.color,
            moves=result.candidates[decision.selected_index],
            start_signature=engine_state_signature(engine),
            score=decision.logits[decision.selected_index],
            metadata={
                "candidate_count": len(result.candidates),
                "selected_index": decision.selected_index,
                "explored_states": result.explored_states,
                "search_complete": not result.exhausted,
                "search_termination_reason": result.termination_reason,
                "inference_ms": decision.inference_ms,
                "neural_value": decision.value,
            },
            warning=warning,
        )


__all__ = ["NeuralDecision", "NeuralPolicyValueAgent"]
