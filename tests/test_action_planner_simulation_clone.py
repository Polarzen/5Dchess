from copy import deepcopy

from src.ai.action_planner import ActionPlanner, ActionSearchBudget, engine_state_signature
from src.engine.action import ActionRules
from src.engine.board import Position
from src.engine.engine import FiveDEngine
from src.engine.timeline import Timeline
from src.utils.constants import ChessColor, GameState


def _position(timeline_id, time_point, side, *pieces, unmoved_pawns=None):
    board = [["" for _ in range(8)] for _ in range(8)]
    board[7][7] = "K"
    board[0][7] = "k"
    for x, y, char in pieces:
        board[y][x] = char
    return Position(
        board=board,
        turn=side,
        timeline_id=timeline_id,
        time_point=time_point,
        unmoved_pawns=set() if unmoved_pawns is None else set(unmoved_pawns),
    )


def _engine_with_timelines(timelines, color=ChessColor.WHITE):
    engine = FiveDEngine()
    manager = engine.timeline_manager
    manager.timelines = {timeline.timeline_id: timeline for timeline in timelines}
    manager.active_timeline_id = 0
    manager._next_positive_id = max([1, *(tid + 1 for tid in manager.timelines if tid > 0)])
    manager._next_negative_id = min([-1, *(tid - 1 for tid in manager.timelines if tid < 0)])
    manager.refresh_activity()
    engine.game_state = GameState.PLAYING
    engine.move_history = []
    engine.action_history = []
    engine.move_counter = 0
    engine.current_turn_color = color
    engine.current_action = ActionRules.begin(color, manager.timelines)
    return engine


def _branching_engine():
    old = _position(0, 0, ChessColor.WHITE)
    latest = _position(0, 2, ChessColor.WHITE, (3, 3, "R"))
    timeline = Timeline(timeline_id=0)
    timeline.add_position(old)
    timeline.add_position(latest)
    return _engine_with_timelines([timeline])


def _multi_required_engine():
    first = Timeline(timeline_id=0)
    first.add_position(
        _position(0, 0, ChessColor.WHITE, (4, 6, "P"), unmoved_pawns={(4, 6)})
    )
    second = Timeline(timeline_id=1, owner=ChessColor.WHITE)
    second.add_position(
        _position(1, 0, ChessColor.WHITE, (4, 6, "P"), unmoved_pawns={(4, 6)})
    )
    return _engine_with_timelines([first, second])


def _run_with_clone(engine, budget, clone_impl, monkeypatch):
    monkeypatch.setattr(FiveDEngine, "clone_for_simulation", clone_impl)
    return ActionPlanner(budget).search(engine)


def _assert_same_search(engine, budget, monkeypatch):
    original = FiveDEngine.clone_for_simulation
    before = engine_state_signature(engine)

    def legacy_clone(state):
        return deepcopy(state)

    expected = _run_with_clone(engine, budget, legacy_clone, monkeypatch)
    assert engine_state_signature(engine) == before
    monkeypatch.setattr(FiveDEngine, "clone_for_simulation", original)
    actual = ActionPlanner(budget).search(engine)
    assert engine_state_signature(engine) == before
    assert actual.candidates == expected.candidates
    assert actual.explored_states == expected.explored_states
    assert actual.termination_reason == expected.termination_reason
    return actual


def test_initial_search_matches_deepcopy_oracle_exactly(monkeypatch):
    result = _assert_same_search(
        FiveDEngine(),
        ActionSearchBudget(
            max_states=256, max_actions=24, max_move_depth=8, max_seconds=None
        ),
        monkeypatch,
    )
    assert result.candidates


def test_branching_search_matches_deepcopy_oracle_exactly(monkeypatch):
    result = _assert_same_search(
        _branching_engine(),
        ActionSearchBudget(
            max_states=128, max_actions=24, max_move_depth=6, max_seconds=None
        ),
        monkeypatch,
    )
    assert result.candidates
    assert any(
        any(spec.source.board.turn != spec.destination.board.turn for spec in candidate)
        for candidate in result.candidates
    )


def test_multi_required_search_matches_deepcopy_oracle_exactly(monkeypatch):
    result = _assert_same_search(
        _multi_required_engine(),
        ActionSearchBudget(
            max_states=128, max_actions=24, max_move_depth=6, max_seconds=None
        ),
        monkeypatch,
    )
    assert result.candidates
    assert any(len(candidate) >= 2 for candidate in result.candidates)


def test_state_budget_termination_matches_deepcopy_oracle(monkeypatch):
    result = _assert_same_search(
        FiveDEngine(),
        ActionSearchBudget(
            max_states=7, max_actions=24, max_move_depth=8, max_seconds=None
        ),
        monkeypatch,
    )
    assert result.termination_reason == "state_budget"


def test_action_budget_termination_matches_deepcopy_oracle(monkeypatch):
    result = _assert_same_search(
        FiveDEngine(),
        ActionSearchBudget(
            max_states=256, max_actions=3, max_move_depth=8, max_seconds=None
        ),
        monkeypatch,
    )
    assert result.termination_reason == "action_budget"
    assert len(result.candidates) == 3


def test_depth_budget_behavior_matches_deepcopy_oracle(monkeypatch):
    _assert_same_search(
        _multi_required_engine(),
        ActionSearchBudget(
            max_states=256, max_actions=24, max_move_depth=1, max_seconds=None
        ),
        monkeypatch,
    )
