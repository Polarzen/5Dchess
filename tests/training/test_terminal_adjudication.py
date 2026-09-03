from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("safetensors")

from src.ai.action_planner import ActionPlanningError, ActionSearchBudget, ActionSearchResult
from src.engine.engine import FiveDEngine
from src.engine.outcome_rules import OutcomeKind, OutcomeRules
from src.engine.royal_rules import RoyalRules
from src.training.agent import NeuralPolicyValueAgent
from src.training.arena import _candidate_stats, evaluate_arena, main as arena_main
from src.training.checkpoint import save_checkpoint
from src.training.config import PlannerConfig, model_preset
from src.training.model import PolicyValueModel
from src.training.selfplay import generate_selfplay


def _tiny_checkpoint(path):
    model = PolicyValueModel(model_preset("tiny"))
    save_checkpoint(
        path,
        model,
        epoch=0,
        global_step=0,
        seed=1,
        best_validation_loss=None,
        training_config={},
    )


def test_outcome_classifier_reuses_proven_no_action_without_search(monkeypatch):
    engine = FiveDEngine()
    monkeypatch.setattr(RoyalRules, "is_in_check", lambda self, color: True)

    outcome = OutcomeRules.classify_proven_no_legal_action(
        engine,
        explored_states=17,
    )

    assert outcome.kind == OutcomeKind.CHECKMATE
    assert outcome.loser == engine.current_turn_color
    assert outcome.winner == engine.current_turn_color.opposite()
    assert outcome.in_check is True
    assert outcome.explored_states == 17


def test_arena_complete_no_action_is_terminal_not_planning_failure(
    tmp_path, monkeypatch
):
    checkpoint = tmp_path / "checkpoint"
    _tiny_checkpoint(checkpoint)

    def proven_no_action(self, engine):
        raise ActionPlanningError(
            "no_legal_action",
            incomplete=False,
            explored_states=23,
        )

    monkeypatch.setattr(NeuralPolicyValueAgent, "plan_action", proven_no_action)
    monkeypatch.setattr(RoyalRules, "is_in_check", lambda self, color: False)

    result = evaluate_arena(
        checkpoint=checkpoint,
        opponent="easy",
        games=1,
        device_name="cpu",
        seed=9,
        max_actions=1,
        budget=ActionSearchBudget(
            max_states=64,
            max_actions=4,
            max_move_depth=4,
            max_seconds=0.25,
        ),
    )

    assert result["draws"] == 1
    assert result["planning_failure_count"] == 0
    assert result["budget_termination_count"] == 0
    assert result["illegal_action_count"] == 0
    assert result["unexpected_failure_count"] == 0
    assert result["proven_terminal_adjudication_count"] == 1
    assert result["first_failure"] is None
    assert result["candidate_breadth"]["neural_actions"]["observations"] == 0


def test_candidate_stats_report_min_median_mean_max():
    assert _candidate_stats([1, 4, 24, 24]) == {
        "observations": 4,
        "minimum": 1,
        "median": 14.0,
        "mean": 13.25,
        "maximum": 24,
    }


def test_arena_cli_fails_when_planning_failure_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.training.arena.evaluate_arena",
        lambda **kwargs: {
            "illegal_action_count": 0,
            "stale_failure_count": 0,
            "planning_failure_count": 1,
            "unexpected_failure_count": 0,
        },
    )

    assert arena_main(["--checkpoint", str(tmp_path / "unused")]) == 1


def test_selfplay_complete_no_action_gets_terminal_label(tmp_path, monkeypatch):
    def proven_no_action(self, engine):
        return ActionSearchResult(
            candidates=(),
            explored_states=11,
            termination_reason=None,
        )

    monkeypatch.setattr("src.training.selfplay.ActionPlanner.search", proven_no_action)
    monkeypatch.setattr(RoyalRules, "is_in_check", lambda self, color: False)

    result = generate_selfplay(
        games=1,
        teacher="easy",
        output=tmp_path / "dataset",
        seed=5,
        max_actions=1,
        planner_config=PlannerConfig(
            max_states=64,
            max_actions=4,
            max_move_depth=4,
            max_seconds=0.1,
        ),
        shard_size=8,
        deterministic_planner=True,
    )

    assert result["games_generated"] == 1
    assert result["sample_count"] == 0
    assert result["termination_counts"] == {"stalemate": 1}
