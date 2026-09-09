"""Regression coverage for ActionPlanner wall-clock budget boundaries."""

import src.ai.action_planner as action_planner_module
from src.ai import ActionPlanner, ActionSearchBudget
from src.engine import FiveDEngine


def _submit_capable_partial_action() -> FiveDEngine:
    engine = FiveDEngine()
    position = engine.get_current_position()
    move = engine.get_legal_moves(position)[0]
    assert engine.execute_action_move(move)
    assert engine.get_required_action_boards() == ()
    return engine


def test_expired_wall_budget_skips_submit_validation(monkeypatch):
    engine = _submit_capable_partial_action()

    def forbidden_submit_query(self):
        raise AssertionError("expired planner entered can_submit_action")

    monkeypatch.setattr(FiveDEngine, "can_submit_action", forbidden_submit_query)
    result = ActionPlanner(ActionSearchBudget(
        max_states=256,
        max_actions=24,
        max_move_depth=32,
        max_seconds=0.0,
    )).search(engine)

    assert result.candidates == ()
    assert result.termination_reason == "time_budget"


def test_submit_witness_crossing_wall_deadline_is_not_accepted(monkeypatch):
    engine = _submit_capable_partial_action()
    ticks = iter((100.0, 100.5, 102.0))

    monkeypatch.setattr(
        action_planner_module.time,
        "monotonic",
        lambda: next(ticks),
    )
    monkeypatch.setattr(FiveDEngine, "can_submit_action", lambda self: True)

    result = ActionPlanner(ActionSearchBudget(
        max_states=256,
        max_actions=24,
        max_move_depth=32,
        max_seconds=1.0,
    )).search(engine)

    assert result.candidates == ()
    assert result.termination_reason == "time_budget"
    assert result.explored_states == 0
