"""Deepcopy oracle and isolation coverage for Outcome ActionSearch cloning."""
from __future__ import annotations

from copy import deepcopy

from src.ai.action_planner import engine_state_signature
from src.engine.action import ActionRules
from src.engine.action_search import ActionSearch, ActionSearchResult
from src.engine.board import Position
from src.engine.engine import FiveDEngine
from src.engine.timeline import Timeline, TimelineManager
from src.utils.constants import ChessColor, GameState


class LegacyDeepcopyActionSearch(ActionSearch):
    """Test-only snapshot of the pre-optimization ActionSearch clone behavior."""

    def find_legal_action(
        self,
        engine: FiveDEngine,
        color: ChessColor | None = None,
    ) -> ActionSearchResult:
        state = deepcopy(engine)
        state.game_state = GameState.PLAYING
        if color is None:
            color = state.current_turn_color
        state.current_turn_color = color
        state.timeline_manager.refresh_activity()
        state.current_action = ActionRules.begin(
            color,
            state.timeline_manager.timelines,
        )

        self._reset_search()
        witness = self._dfs(state, depth=0)
        return ActionSearchResult(
            has_legal_action=witness is not None,
            explored_states=self._explored_states,
            witness=witness or (),
            termination_reason=self._termination_reason,
        )

    def find_legal_completion(self, engine: FiveDEngine) -> ActionSearchResult:
        state = deepcopy(engine)
        state.game_state = GameState.PLAYING
        state.timeline_manager.refresh_activity()
        state._ensure_current_action()

        self._reset_search()
        witness = self._dfs(state, depth=0)
        return ActionSearchResult(
            has_legal_action=witness is not None,
            explored_states=self._explored_states,
            witness=witness or (),
            termination_reason=self._termination_reason,
        )

    def _search_move(
        self,
        state: FiveDEngine,
        move,
        depth: int,
    ):
        if self._termination_reason is not None:
            return None
        child = deepcopy(state)
        if not child.execute_action_move(move):
            return None
        return self._dfs(child, depth=depth + 1)


def _position(
    timeline_id: int,
    time_point: int,
    side: ChessColor,
    *pieces: tuple[int, int, str],
    unmoved_pawns=None,
) -> Position:
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
        castling_rights={
            "white_kingside": False,
            "white_queenside": False,
            "black_kingside": False,
            "black_queenside": False,
        },
    )


def _timeline(
    timeline_id: int,
    *positions: Position,
    owner: ChessColor | None = None,
) -> Timeline:
    result = Timeline(timeline_id=timeline_id, owner=owner)
    for position in positions:
        result.add_position(position)
    return result


def _engine_with_timelines(
    timelines: list[Timeline],
    color: ChessColor = ChessColor.WHITE,
) -> FiveDEngine:
    engine = FiveDEngine()
    manager = TimelineManager(max_timelines=engine.max_timelines)
    manager.timelines = {timeline.timeline_id: timeline for timeline in timelines}
    manager.active_timeline_id = 0 if 0 in manager.timelines else timelines[0].timeline_id
    manager._next_positive_id = max(
        [1, *(timeline_id + 1 for timeline_id in manager.timelines if timeline_id > 0)]
    )
    manager._next_negative_id = min(
        [-1, *(timeline_id - 1 for timeline_id in manager.timelines if timeline_id < 0)]
    )
    manager.refresh_activity()
    engine.timeline_manager = manager
    engine.game_state = GameState.PLAYING
    engine.move_history = []
    engine.action_history = []
    engine.move_counter = 0
    engine.current_turn_color = color
    engine.current_action = ActionRules.begin(color, manager.timelines)
    return engine


def _branching_engine() -> FiveDEngine:
    old = _position(0, 0, ChessColor.WHITE)
    latest = _position(0, 2, ChessColor.WHITE, (3, 3, "R"))
    return _engine_with_timelines([_timeline(0, old, latest)])


def _multi_required_engine() -> FiveDEngine:
    first = _timeline(
        0,
        _position(
            0,
            0,
            ChessColor.WHITE,
            (4, 6, "P"),
            unmoved_pawns={(4, 6)},
        ),
    )
    second = _timeline(
        1,
        _position(
            1,
            0,
            ChessColor.WHITE,
            (4, 6, "P"),
            unmoved_pawns={(4, 6)},
        ),
        owner=ChessColor.WHITE,
    )
    return _engine_with_timelines([first, second])


def _terminal_engine(*, stalemate: bool) -> FiveDEngine:
    if stalemate:
        position = _position(
            0,
            0,
            ChessColor.WHITE,
            (6, 5, "q"),
            (5, 6, "k"),
        )
        position.board[7][7] = "K"
    else:
        position = _position(
            0,
            0,
            ChessColor.WHITE,
            (6, 6, "q"),
            (5, 5, "k"),
        )
        position.board[7][7] = "K"
    return _engine_with_timelines([_timeline(0, position)])


def _cross_timeline_escape_engine() -> FiveDEngine:
    historical = _position(0, 0, ChessColor.WHITE)
    locally_stalemated = _position(
        0,
        2,
        ChessColor.WHITE,
        (6, 5, "q"),
        (5, 6, "k"),
    )
    rescue = _position(-1, 2, ChessColor.WHITE, (4, 4, "B"))
    return _engine_with_timelines(
        [
            _timeline(0, historical, locally_stalemated),
            _timeline(-1, rescue, owner=ChessColor.BLACK),
        ]
    )


def _signature(engine: FiveDEngine):
    return engine_state_signature(engine), getattr(engine, "rule_warning", None)


def _assert_same_search(engine: FiveDEngine, **limits) -> ActionSearchResult:
    before = _signature(engine)
    expected = LegacyDeepcopyActionSearch(**limits).find_legal_action(engine)
    assert _signature(engine) == before
    actual = ActionSearch(**limits).find_legal_action(engine)
    assert _signature(engine) == before
    assert actual == expected
    return actual


def test_initial_search_matches_deepcopy_oracle_exactly():
    result = _assert_same_search(
        FiveDEngine(), max_states=256, max_depth=16, max_seconds=None
    )
    assert result.has_legal_action
    assert result.witness


def test_checkmate_and_stalemate_match_deepcopy_oracle_exactly():
    mate = _assert_same_search(
        _terminal_engine(stalemate=False),
        max_states=256,
        max_depth=16,
        max_seconds=None,
    )
    stale = _assert_same_search(
        _terminal_engine(stalemate=True),
        max_states=256,
        max_depth=16,
        max_seconds=None,
    )
    assert not mate.has_legal_action
    assert not stale.has_legal_action
    assert mate.termination_reason is None
    assert stale.termination_reason is None


def test_branching_and_cross_timeline_search_match_deepcopy_oracle_exactly():
    branching = _assert_same_search(
        _branching_engine(), max_states=256, max_depth=16, max_seconds=None
    )
    cross = _assert_same_search(
        _cross_timeline_escape_engine(),
        max_states=256,
        max_depth=16,
        max_seconds=None,
    )
    assert branching.has_legal_action
    assert cross.has_legal_action
    assert any(move.is_branching or move.is_cross_timeline for move in cross.witness)


def test_multi_move_action_matches_deepcopy_oracle_exactly():
    result = _assert_same_search(
        _multi_required_engine(), max_states=256, max_depth=16, max_seconds=None
    )
    assert result.has_legal_action
    assert len(result.witness) >= 2


def test_state_depth_and_time_budget_behavior_matches_deepcopy_oracle():
    state_limited = _assert_same_search(
        _multi_required_engine(), max_states=1, max_depth=16, max_seconds=None
    )
    depth_limited = _assert_same_search(
        _multi_required_engine(), max_states=256, max_depth=1, max_seconds=None
    )
    time_limited = _assert_same_search(
        FiveDEngine(), max_states=256, max_depth=16, max_seconds=0.0
    )
    assert state_limited.termination_reason == "state_budget"
    assert depth_limited.termination_reason == "depth_limit"
    assert time_limited.termination_reason == "time_budget"
    assert not time_limited.has_legal_action


def test_partial_completion_matches_deepcopy_oracle_and_keeps_source_unchanged():
    engine = FiveDEngine()
    position = engine.timeline_manager.get_timeline(0).get_position(0)
    move = engine.get_legal_moves(position)[0]
    assert engine.execute_action_move(move)
    before = _signature(engine)

    expected = LegacyDeepcopyActionSearch(
        max_states=256, max_depth=16, max_seconds=None
    ).find_legal_completion(engine)
    actual = ActionSearch(
        max_states=256, max_depth=16, max_seconds=None
    ).find_legal_completion(engine)

    assert actual == expected
    assert _signature(engine) == before


def test_search_move_siblings_start_from_same_unmodified_parent():
    engine = _branching_engine()
    position = engine.timeline_manager.get_timeline(0).latest_position
    moves = engine.get_legal_moves(position)
    branching = next(move for move in moves if move.is_branching)
    ordinary = next(move for move in moves if not move.is_branching)
    before = _signature(engine)

    class CaptureChildren(ActionSearch):
        def __init__(self):
            super().__init__(max_states=32, max_depth=8, max_seconds=None)
            self.children = []

        def _dfs(self, state, depth):
            self.children.append((_signature(state), len(state.timeline_manager.timelines)))
            return None

    search = CaptureChildren()
    search._search_move(engine, branching, 0)
    search._search_move(engine, ordinary, 0)

    assert _signature(engine) == before
    assert len(search.children) == 2
    assert search.children[0][1] > len(engine.timeline_manager.timelines)
    assert search.children[1][1] == len(engine.timeline_manager.timelines)
