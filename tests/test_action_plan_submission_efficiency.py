"""Regression coverage for Action-plan submission validation boundaries."""

from src.ai import ActionSearchBudget, RandomAI, apply_action_plan
from src.engine import FiveDEngine
from src.utils.constants import ChessColor


def test_apply_action_plan_relies_on_submit_action_for_final_validation(monkeypatch):
    engine = FiveDEngine()
    plan = RandomAI(
        ChessColor.WHITE,
        seed=7,
        budget=ActionSearchBudget(
            max_states=256,
            max_actions=8,
            max_move_depth=8,
            max_seconds=1.0,
        ),
    ).plan_action(engine)

    def forbidden_preflight(self):
        raise AssertionError(
            "apply_action_plan must not call can_submit_action before submit_action"
        )

    # Plan construction legitimately uses can_submit_action. Patch only after a
    # complete plan exists so this guards the application boundary specifically.
    monkeypatch.setattr(FiveDEngine, "can_submit_action", forbidden_preflight)

    applied = apply_action_plan(engine, plan)

    assert applied
    assert engine.current_turn_color == ChessColor.BLACK
    assert len(engine.action_history) == 1
    assert engine.action_history[0].submitted
