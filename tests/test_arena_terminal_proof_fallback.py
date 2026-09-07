from types import SimpleNamespace

from src.ai.action_planner import ActionPlanningError
from src.engine.action_search import ActionSearch
from src.engine.outcome_rules import OutcomeKind, OutcomeRules
from src.training.arena import _adjudicate_incomplete_planner_terminal
from src.utils.constants import ChessColor, GameState


class _Engine:
    def __init__(self):
        self.current_turn_color = ChessColor.WHITE
        self.game_state = GameState.PLAYING


def _budget_error():
    return ActionPlanningError(
        "state_budget", incomplete=True, explored_states=1024
    )


def test_incomplete_planner_error_adjudicates_only_after_complete_no_action_proof(monkeypatch):
    engine = _Engine()
    monkeypatch.setattr(
        ActionSearch,
        "find_legal_completion",
        lambda self, candidate: SimpleNamespace(
            has_legal_action=False, exhausted=False, explored_states=3955
        ),
    )
    monkeypatch.setattr(
        OutcomeRules,
        "classify_proven_no_legal_action",
        lambda engine, color, explored_states=0: SimpleNamespace(
            kind=OutcomeKind.STALEMATE
        ),
    )

    assert _adjudicate_incomplete_planner_terminal(engine, _budget_error()) is True
    assert engine.game_state == GameState.STALEMATE


def test_incomplete_terminal_proof_does_not_fabricate_terminal_state(monkeypatch):
    engine = _Engine()
    monkeypatch.setattr(
        ActionSearch,
        "find_legal_completion",
        lambda self, candidate: SimpleNamespace(
            has_legal_action=False, exhausted=True, explored_states=4096
        ),
    )

    assert _adjudicate_incomplete_planner_terminal(engine, _budget_error()) is False
    assert engine.game_state == GameState.PLAYING


def test_found_witness_keeps_original_planning_failure_semantics(monkeypatch):
    engine = _Engine()
    monkeypatch.setattr(
        ActionSearch,
        "find_legal_completion",
        lambda self, candidate: SimpleNamespace(
            has_legal_action=True, exhausted=False, explored_states=1200
        ),
    )

    assert _adjudicate_incomplete_planner_terminal(engine, _budget_error()) is False
    assert engine.game_state == GameState.PLAYING
