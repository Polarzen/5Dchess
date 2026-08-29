"""Regression coverage for Action search/execution loop guards."""

import pytest

from src.ai.alpha_beta import AlphaBetaAI
from src.ai.random_ai import RandomAI
from src.engine import ActionRules, ActionSearch, FiveDEngine, Position, Timeline
from src.utils.constants import ChessColor, GameState


def _install_second_white_present_board(engine: FiveDEngine) -> None:
    other = Timeline(timeline_id=1, owner=ChessColor.WHITE)
    other.add_position(Position.initial(timeline_id=1, time_point=0))
    engine.timeline_manager.timelines[1] = other
    engine.timeline_manager.refresh_activity()
    engine.current_turn_color = ChessColor.WHITE
    engine.current_action = ActionRules.begin(
        ChessColor.WHITE,
        engine.timeline_manager.timelines,
    )


def test_action_search_budget_exhaustion_is_inconclusive():
    engine = FiveDEngine()

    result = ActionSearch(
        max_states=None,
        max_depth=0,
        max_seconds=None,
    ).find_legal_action(engine)

    assert not result.has_legal_action
    assert result.exhausted
    assert result.termination_reason == "depth_limit"
    assert result.explored_states == 0
    # The caller is deep-copied and must remain untouched.
    assert engine.game_state == GameState.PLAYING
    assert engine.move_counter == 0


def test_outcome_search_limit_warns_instead_of_false_terminal(monkeypatch):
    import src.engine.outcome_rules as outcome_module

    engine = FiveDEngine()
    monkeypatch.setattr(
        outcome_module,
        "ActionSearch",
        lambda: ActionSearch(
            max_states=None,
            max_depth=0,
            max_seconds=None,
        ),
    )

    outcome = outcome_module.OutcomeRules.evaluate(engine)

    assert outcome is None
    assert engine.game_state == GameState.PLAYING
    assert "安全上限" in engine.rule_warning
    assert "depth_limit" in engine.rule_warning


def test_alpha_beta_falls_forward_to_remaining_required_board():
    engine = FiveDEngine()
    _install_second_white_present_board(engine)

    first = next(
        move
        for move in engine.get_legal_moves()
        if (
            move.source.timeline == 0
            and move.from_x == 4
            and move.from_y == 6
            and move.to_y == 4
        )
    )
    assert engine.execute_action_move(first)
    assert engine.current_turn_color == ChessColor.WHITE
    assert not engine.can_submit_action()
    assert [coord.timeline for coord in engine.get_required_action_boards()] == [1]

    # Preserve the legacy UI selection on the already-played L0 board.  The old
    # AlphaBeta implementation read get_current_position() here and returned
    # None even though L1 still had required legal moves.
    engine.timeline_manager.active_timeline_id = 0

    ai = AlphaBetaAI(ChessColor.WHITE, search_depth=1)
    move = ai.choose_move(engine)

    assert move is not None
    assert move.source.timeline == 1
    assert move.piece.color == ChessColor.WHITE


def test_ai_action_guard_raises_before_another_state_mutation():
    engine = FiveDEngine()
    ai = RandomAI(ChessColor.WHITE)
    action = engine.current_action
    assert action is not None

    move_limit = max(16, engine.max_timelines + 8)
    action.moves.extend([None] * move_limit)  # type: ignore[list-item]
    before_move_counter = engine.move_counter

    with pytest.raises(RuntimeError, match="AI Action safety guard"):
        ai.choose_move(engine)

    assert engine.move_counter == before_move_counter
