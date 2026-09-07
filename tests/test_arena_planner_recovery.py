from types import SimpleNamespace

import src.training.arena as arena_module
from src.ai.action_planner import AIActionPlan, ActionPlanningError
from src.engine.action_search import ActionSearch
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.move_generator import Move
from src.engine.outcome_rules import OutcomeKind, OutcomeRules
from src.engine.piece import Piece
from src.training.arena import _recover_incomplete_planner_action
from src.utils.constants import ChessColor, GameState, PieceType


class _Engine:
    def __init__(self):
        self.current_turn_color = ChessColor.WHITE
        self.game_state = GameState.PLAYING


def _budget_error():
    return ActionPlanningError(
        "time_budget", incomplete=True, explored_states=321
    )


def _move():
    board = BoardCoord(0, 0, ChessColor.WHITE)
    return Move(
        piece=Piece(PieceType.KING, ChessColor.WHITE),
        source=Square5D(board, 1, 1),
        destination=Square5D(board, 1, 2),
    )


def test_recovery_returns_canonical_plan_for_proven_witness(monkeypatch):
    engine = _Engine()
    monkeypatch.setattr(
        ActionSearch,
        "find_legal_completion",
        lambda self, candidate: SimpleNamespace(
            has_legal_action=True,
            exhausted=False,
            explored_states=777,
            witness=(_move(),),
            termination_reason=None,
        ),
    )
    monkeypatch.setattr(
        arena_module, "engine_state_signature", lambda candidate: ("sig",)
    )

    kind, plan = _recover_incomplete_planner_action(engine, _budget_error())

    assert kind == "witness"
    assert isinstance(plan, AIActionPlan)
    assert len(plan.moves) == 1
    assert plan.metadata["arena_recovery"] is True
    assert plan.metadata["planner_explored_states"] == 321
    assert engine.game_state == GameState.PLAYING


def test_recovery_keeps_failure_when_proof_is_inconclusive(monkeypatch):
    engine = _Engine()
    monkeypatch.setattr(
        ActionSearch,
        "find_legal_completion",
        lambda self, candidate: SimpleNamespace(
            has_legal_action=False,
            exhausted=True,
            explored_states=4096,
            witness=(),
            termination_reason="state_budget",
        ),
    )

    kind, plan = _recover_incomplete_planner_action(engine, _budget_error())

    assert kind == "unresolved"
    assert plan is None
    assert engine.game_state == GameState.PLAYING


def test_recovery_adjudicates_complete_no_action_proof(monkeypatch):
    engine = _Engine()
    monkeypatch.setattr(
        ActionSearch,
        "find_legal_completion",
        lambda self, candidate: SimpleNamespace(
            has_legal_action=False,
            exhausted=False,
            explored_states=3955,
            witness=(),
            termination_reason=None,
        ),
    )
    monkeypatch.setattr(
        OutcomeRules,
        "classify_proven_no_legal_action",
        lambda engine, color, explored_states=0: SimpleNamespace(
            kind=OutcomeKind.STALEMATE
        ),
    )

    kind, plan = _recover_incomplete_planner_action(engine, _budget_error())

    assert kind == "terminal"
    assert plan is None
    assert engine.game_state == GameState.STALEMATE
