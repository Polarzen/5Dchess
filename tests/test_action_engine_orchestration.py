"""Integration tests for FiveDEngine Action / Submit orchestration."""

from src.engine import ActionRules, BoardCoord, FiveDEngine, Move, Piece, Position, Square5D, Timeline
from src.utils.constants import ChessColor, PieceType


def _empty_position(
    timeline_id: int,
    time_point: int,
    side: ChessColor,
) -> Position:
    board = [["" for _ in range(8)] for _ in range(8)]
    board[7][7] = "K"
    board[0][7] = "k"
    return Position(
        board=board,
        turn=side,
        timeline_id=timeline_id,
        time_point=time_point,
        unmoved_pawns=set(),
    )


def _timeline_through(timeline_id: int, latest_time: int, owner=None) -> Timeline:
    timeline = Timeline(timeline_id=timeline_id, owner=owner)
    for time_point in range(latest_time + 1):
        side = ChessColor.WHITE if time_point % 2 == 0 else ChessColor.BLACK
        timeline.add_position(_empty_position(timeline_id, time_point, side))
    return timeline


def _reset_action(engine: FiveDEngine, color: ChessColor = ChessColor.WHITE) -> None:
    engine.current_turn_color = color
    engine.action_history = []
    engine.current_action = ActionRules.begin(color, engine.timeline_manager.timelines)


def test_execute_action_move_waits_for_explicit_submit():
    engine = FiveDEngine()
    white_double = next(
        move for move in engine.get_legal_moves()
        if move.from_x == 4 and move.from_y == 6 and move.to_y == 4
    )

    assert engine.execute_action_move(white_double)
    assert engine.current_turn_color == ChessColor.WHITE
    assert engine.current_action is not None
    assert len(engine.current_action.moves) == 1
    assert engine.can_submit_action()

    assert engine.submit_action()
    assert engine.current_turn_color == ChessColor.BLACK
    assert len(engine.action_history) == 1
    assert engine.action_history[0].submitted
    assert engine.current_action is not None
    assert engine.current_action.color == ChessColor.BLACK
    assert engine.current_action.moves == []


def test_compat_execute_move_auto_submits_when_present_has_shifted():
    engine = FiveDEngine()
    white_double = next(
        move for move in engine.get_legal_moves()
        if move.from_x == 4 and move.from_y == 6 and move.to_y == 4
    )

    assert engine.execute_move(white_double)
    assert engine.current_turn_color == ChessColor.BLACK
    assert len(engine.action_history) == 1
    assert engine.action_history[0].moves == [white_double]


def test_multiple_present_boards_keep_same_action_open_until_all_advance():
    engine = FiveDEngine()
    manager = engine.timeline_manager
    main = manager.get_timeline(0)
    main.positions.clear()

    white_rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    main_start = _empty_position(0, 0, ChessColor.WHITE)
    main_start.set_piece(0, 6, white_rook)
    main.add_position(main_start)

    other = Timeline(timeline_id=1, owner=ChessColor.WHITE)
    other_start = _empty_position(1, 0, ChessColor.WHITE)
    other_start.set_piece(1, 6, white_rook)
    other.add_position(other_start)
    manager.timelines[1] = other
    manager.refresh_activity()
    _reset_action(engine)

    first = Move(
        piece=white_rook,
        source=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 0, 6),
        destination=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 0, 5),
    )
    second = Move(
        piece=white_rook,
        source=Square5D(BoardCoord(1, 0, ChessColor.WHITE), 1, 6),
        destination=Square5D(BoardCoord(1, 0, ChessColor.WHITE), 1, 5),
    )

    assert engine.execute_action_move(first)
    assert engine.current_turn_color == ChessColor.WHITE
    assert not engine.can_submit_action()
    assert [board.timeline for board in engine.get_required_action_boards()] == [1]

    assert engine.execute_action_move(second)
    assert engine.current_turn_color == ChessColor.WHITE
    assert engine.can_submit_action()
    assert engine.get_required_action_boards() == ()

    assert engine.submit_action()
    assert engine.current_turn_color == ChessColor.BLACK
    assert len(engine.action_history[0].moves) == 2


def test_optional_future_move_remains_available_after_submit_becomes_legal():
    engine = FiveDEngine()
    manager = engine.timeline_manager
    main = manager.get_timeline(0)
    main.positions.clear()

    rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    main_start = _empty_position(0, 0, ChessColor.WHITE)
    main_start.set_piece(0, 6, rook)
    main.add_position(main_start)

    future = _timeline_through(1, 2, owner=ChessColor.WHITE)
    future.positions[2].set_piece(1, 6, rook)
    manager.timelines[1] = future
    manager.refresh_activity()
    _reset_action(engine)

    present_move = Move(
        piece=rook,
        source=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 0, 6),
        destination=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 0, 5),
    )
    optional_future = Move(
        piece=rook,
        source=Square5D(BoardCoord(1, 1, ChessColor.WHITE), 1, 6),
        destination=Square5D(BoardCoord(1, 1, ChessColor.WHITE), 1, 5),
    )

    assert engine.execute_action_move(present_move)
    assert engine.can_submit_action()
    assert engine.current_turn_color == ChessColor.WHITE

    # Explicit Action API deliberately does not auto-submit, so White can still
    # make its optional move on a future playable White board.
    assert engine.execute_action_move(optional_future)
    assert len(engine.current_action.moves) == 2
    assert engine.can_submit_action()
    assert engine.submit_action()


def test_cross_timeline_move_advances_two_present_boards_in_one_move():
    engine = FiveDEngine()
    manager = engine.timeline_manager
    main = manager.get_timeline(0)
    main.positions.clear()

    rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    source = _empty_position(0, 0, ChessColor.WHITE)
    source.set_piece(3, 3, rook)
    main.add_position(source)

    target_timeline = Timeline(timeline_id=1, owner=ChessColor.WHITE)
    target = _empty_position(1, 0, ChessColor.WHITE)
    target_timeline.add_position(target)
    manager.timelines[1] = target_timeline
    manager.refresh_activity()
    _reset_action(engine)

    move = Move(
        piece=rook,
        source=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 3, 3),
        destination=Square5D(BoardCoord(1, 0, ChessColor.WHITE), 3, 3),
    )

    assert engine.execute_action_move(move)
    assert main.latest_time == 1
    assert target_timeline.latest_time == 1
    assert engine.can_submit_action()
    assert engine.get_required_action_boards() == ()


def test_get_legal_moves_falls_forward_to_an_unplayed_required_board():
    engine = FiveDEngine()
    manager = engine.timeline_manager

    other = Timeline(timeline_id=1, owner=ChessColor.WHITE)
    other.add_position(Position.initial(timeline_id=1, time_point=0))
    manager.timelines[1] = other
    manager.refresh_activity()
    _reset_action(engine)

    first = next(
        move for move in engine.get_legal_moves()
        if move.from_x == 4 and move.from_y == 6 and move.to_y == 4
    )
    assert first.source.timeline == 0
    assert engine.execute_action_move(first)
    assert not engine.can_submit_action()

    remaining_moves = engine.get_legal_moves()
    assert remaining_moves
    assert all(move.source.timeline == 1 for move in remaining_moves)
    assert all(move.piece.color == ChessColor.WHITE for move in remaining_moves)


def test_current_action_rejects_opponent_move_even_if_board_is_playable():
    engine = FiveDEngine()
    black_pawn = Piece(PieceType.PAWN, ChessColor.BLACK)
    illegal = Move(
        piece=black_pawn,
        source=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 4, 1),
        destination=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 4, 2),
    )

    assert not engine.execute_action_move(illegal)
    assert engine.move_counter == 0
    assert engine.move_history == []


def test_game_summary_exposes_present_and_action_progress():
    engine = FiveDEngine()
    summary = engine.get_game_summary()

    assert summary["present"]["time_point"] == 0
    assert summary["present"]["side"] == "white"
    assert summary["present"]["timelines"] == [0]
    assert summary["current_action_moves"] == 0
    assert summary["required_action_boards"] == ["L0:T0w"]
    assert not summary["can_submit_action"]
