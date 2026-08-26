"""Action-level 5D Checkmate / Stalemate regression tests."""
from __future__ import annotations

from src.engine import (
    ActionRules,
    ActionSearch,
    FiveDEngine,
    OutcomeKind,
    OutcomeRules,
    Position,
    Timeline,
    TimelineManager,
)
from src.utils.constants import ChessColor, GameState


def make_position(
    timeline_id: int,
    time_point: int,
    pieces: dict[tuple[int, int], str],
) -> Position:
    board = [["" for _ in range(8)] for _ in range(8)]
    for (x, y), piece in pieces.items():
        board[y][x] = piece
    return Position(
        board=board,
        turn=(ChessColor.WHITE if time_point % 2 == 0 else ChessColor.BLACK),
        timeline_id=timeline_id,
        time_point=time_point,
        castling_rights={
            "white_kingside": False,
            "white_queenside": False,
            "black_kingside": False,
            "black_queenside": False,
        },
    )


def timeline_with(
    timeline_id: int,
    *positions: Position,
    owner: ChessColor | None = None,
) -> Timeline:
    timeline = Timeline(timeline_id=timeline_id, owner=owner)
    for position in positions:
        timeline.add_position(position)
    return timeline


def install_state(
    engine: FiveDEngine,
    timelines: list[Timeline],
    color: ChessColor,
) -> FiveDEngine:
    manager = TimelineManager(max_timelines=engine.max_timelines)
    manager.timelines = {timeline.timeline_id: timeline for timeline in timelines}
    manager.active_timeline_id = 0 if 0 in manager.timelines else timelines[0].timeline_id
    manager.refresh_activity()

    engine.timeline_manager = manager
    engine.game_state = GameState.PLAYING
    engine.move_history = []
    engine.action_history = []
    engine.move_counter = 0
    engine.current_turn_color = color
    engine.current_action = ActionRules.begin(color, manager.timelines)
    return engine


def test_initial_position_has_complete_legal_action():
    engine = FiveDEngine()

    result = ActionSearch().find_legal_action(engine)

    assert result.has_legal_action
    assert result.witness
    assert result.explored_states >= 1
    # Search operates on deep copies and must not advance real history.
    assert engine.timeline_manager.get_timeline(0).latest_time == 0
    assert engine.move_counter == 0


def test_single_timeline_checkmate_requires_no_legal_action_and_check():
    # White: Kh1. Black: Qg2 + Kf3. White is checked and every king move is
    # either occupied/protected or attacked.
    position = make_position(
        0,
        0,
        {
            (7, 7): "K",  # h1
            (6, 6): "q",  # g2
            (5, 5): "k",  # f3 protects g2
        },
    )
    engine = install_state(
        FiveDEngine(),
        [timeline_with(0, position)],
        ChessColor.WHITE,
    )

    search = OutcomeRules.has_legal_action(engine)
    outcome = OutcomeRules.evaluate(engine)

    assert not search.has_legal_action
    assert outcome is not None
    assert outcome.kind == OutcomeKind.CHECKMATE
    assert outcome.in_check
    assert outcome.loser == ChessColor.WHITE
    assert outcome.winner == ChessColor.BLACK


def test_single_timeline_stalemate_requires_no_legal_action_without_check():
    # White: Kh1. Black: Qg3 + Kf2. Kh1 is not attacked, but g1/h2/g2 are.
    position = make_position(
        0,
        0,
        {
            (7, 7): "K",  # h1
            (6, 5): "q",  # g3
            (5, 6): "k",  # f2
        },
    )
    engine = install_state(
        FiveDEngine(),
        [timeline_with(0, position)],
        ChessColor.WHITE,
    )

    search = OutcomeRules.has_legal_action(engine)
    outcome = OutcomeRules.evaluate(engine)

    assert not search.has_legal_action
    assert outcome is not None
    assert outcome.kind == OutcomeKind.STALEMATE
    assert not outcome.in_check
    assert outcome.loser is None
    assert outcome.winner is None


def test_board_stalemate_is_not_global_when_other_timeline_can_escape():
    # L0 is locally stalemated at t2.  L-1 is also in the White Present and has
    # a Bishop that can make a cross-board/time-travel move.  Such a move can
    # consume/rewind the Present, so the position is not a global stalemate.
    historical = make_position(
        0,
        0,
        {
            (0, 7): "K",
            (7, 0): "k",
        },
    )
    locally_stalemated = make_position(
        0,
        2,
        {
            (7, 7): "K",  # h1
            (6, 5): "q",  # g3
            (5, 6): "k",  # f2
        },
    )
    rescue_board = make_position(
        -1,
        2,
        {
            (4, 4): "B",
        },
    )

    engine = install_state(
        FiveDEngine(),
        [
            timeline_with(0, historical, locally_stalemated),
            timeline_with(-1, rescue_board, owner=ChessColor.BLACK),
        ],
        ChessColor.WHITE,
    )

    result = ActionSearch().find_legal_action(engine)

    assert result.has_legal_action
    assert result.witness
    assert any(move.is_cross_timeline or move.is_branching for move in result.witness)
    assert OutcomeRules.evaluate(engine) is None


def test_submit_sets_engine_checkmate_from_complete_action_search():
    # Black plays Qg3-g2, producing the Kh1 / Qg2 / Kf3 checkmate above.
    position = make_position(
        0,
        1,
        {
            (7, 7): "K",  # h1
            (6, 5): "q",  # g3
            (5, 5): "k",  # f3
        },
    )
    engine = install_state(
        FiveDEngine(),
        [timeline_with(0, position)],
        ChessColor.BLACK,
    )

    move = next(
        move
        for move in engine.get_legal_moves(position)
        if (
            move.source.x,
            move.source.y,
            move.destination.x,
            move.destination.y,
        ) == (6, 5, 6, 6)
    )

    assert engine.execute_move(move)
    assert engine.current_turn_color == ChessColor.WHITE
    assert engine.game_state == GameState.CHECKMATE


def test_submit_sets_engine_stalemate_from_complete_action_search():
    # Black plays Qf4-g3, producing the Kh1 / Qg3 / Kf2 stalemate above.
    position = make_position(
        0,
        1,
        {
            (7, 7): "K",  # h1
            (5, 4): "q",  # f4
            (5, 6): "k",  # f2
        },
    )
    engine = install_state(
        FiveDEngine(),
        [timeline_with(0, position)],
        ChessColor.BLACK,
    )

    move = next(
        move
        for move in engine.get_legal_moves(position)
        if (
            move.source.x,
            move.source.y,
            move.destination.x,
            move.destination.y,
        ) == (5, 4, 6, 5)
    )

    assert engine.execute_move(move)
    assert engine.current_turn_color == ChessColor.WHITE
    assert engine.game_state == GameState.STALEMATE
