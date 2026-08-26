"""Tests for active timelines, The Present, and Action submission rules."""

from src.engine import (
    ActionRules,
    BoardCoord,
    Move,
    Piece,
    Position,
    Square5D,
    Timeline,
    TimelineManager,
    TimelineRules,
)
from src.utils.constants import ChessColor, PieceType


def _position(timeline_id: int, time_point: int, side: ChessColor) -> Position:
    board = [["" for _ in range(8)] for _ in range(8)]
    board[7][4] = "K"
    board[0][4] = "k"
    return Position(
        board=board,
        turn=side,
        timeline_id=timeline_id,
        time_point=time_point,
        unmoved_pawns=set(),
    )


def _timeline(
    timeline_id: int,
    latest_time: int,
    owner: ChessColor | None = None,
) -> Timeline:
    timeline = Timeline(timeline_id=timeline_id, owner=owner)
    for time_point in range(latest_time + 1):
        side = ChessColor.WHITE if time_point % 2 == 0 else ChessColor.BLACK
        timeline.add_position(_position(timeline_id, time_point, side))
    return timeline


def test_extra_same_side_timeline_is_inactive_until_opponent_branches():
    timelines = {
        0: _timeline(0, 4),
        1: _timeline(1, 2, ChessColor.WHITE),
        2: _timeline(2, 0, ChessColor.WHITE),
    }

    TimelineRules.refresh_activity(timelines)
    assert timelines[0].is_active
    assert timelines[1].is_active
    assert not timelines[2].is_active

    timelines[-1] = _timeline(-1, 4, ChessColor.BLACK)
    TimelineRules.refresh_activity(timelines)

    assert timelines[-1].is_active
    assert timelines[2].is_active


def test_timeline_manager_derives_activity_after_branch_creation():
    manager = TimelineManager()
    main = manager.create_initial_timeline()
    main.positions.clear()
    main.add_position(_position(0, 0, ChessColor.WHITE))

    first = manager.create_branch(
        parent_id=0,
        branch_turn=0,
        branch_move_id=1,
        target_time=0,
        creator=ChessColor.WHITE,
    )
    second = manager.create_branch(
        parent_id=0,
        branch_turn=0,
        branch_move_id=2,
        target_time=0,
        creator=ChessColor.WHITE,
    )

    assert first is not None and first.is_active
    assert second is not None and not second.is_active

    black = manager.create_branch(
        parent_id=0,
        branch_turn=0,
        branch_move_id=3,
        target_time=0,
        creator=ChessColor.BLACK,
    )
    assert black is not None and black.is_active
    assert second.is_active


def test_present_is_earliest_playable_active_board_and_ignores_inactive():
    timelines = {
        0: _timeline(0, 6),
        1: _timeline(1, 4, ChessColor.WHITE),
        2: _timeline(2, 0, ChessColor.WHITE),  # inactive without Black branch
    }

    present = TimelineRules.present(timelines)

    assert present is not None
    assert present.legacy_time_point == 4
    assert present.turn == 2
    assert present.side == ChessColor.WHITE
    assert present.timeline_ids == (1,)


def test_present_contains_all_active_boards_in_earliest_column():
    timelines = {
        0: _timeline(0, 2),
        1: _timeline(1, 2, ChessColor.WHITE),
        -1: _timeline(-1, 4, ChessColor.BLACK),
    }

    present = TimelineRules.present(timelines)

    assert present is not None
    assert present.legacy_time_point == 2
    assert present.side == ChessColor.WHITE
    assert set(present.timeline_ids) == {0, 1}


def test_required_boards_are_present_active_boards_only():
    timelines = {
        0: _timeline(0, 2),
        1: _timeline(1, 2, ChessColor.WHITE),
        -1: _timeline(-1, 4, ChessColor.BLACK),
    }

    required = TimelineRules.required_boards(timelines, ChessColor.WHITE)
    assert {board.timeline for board in required} == {0, 1}
    assert TimelineRules.required_boards(timelines, ChessColor.BLACK) == ()


def test_future_and_inactive_playable_boards_are_optional_but_movable():
    timelines = {
        0: _timeline(0, 0),
        1: _timeline(1, 2, ChessColor.WHITE),
        2: _timeline(2, 4, ChessColor.WHITE),  # inactive, but still optional
    }

    movable = TimelineRules.movable_boards(timelines, ChessColor.WHITE)

    assert {(board.timeline, board.legacy_time_point) for board in movable} == {
        (0, 0),
        (1, 2),
        (2, 4),
    }
    assert {board.timeline for board in TimelineRules.required_boards(
        timelines,
        ChessColor.WHITE,
    )} == {0}


def test_action_cannot_submit_until_present_shifts_to_opponent():
    timelines = {
        0: _timeline(0, 0),
        1: _timeline(1, 0, ChessColor.WHITE),
    }
    action = ActionRules.begin(ChessColor.WHITE, timelines)

    assert not ActionRules.can_submit(action, timelines)
    assert {board.timeline for board in ActionRules.required_boards(
        action,
        timelines,
    )} == {0, 1}

    timelines[0].add_position(_position(0, 1, ChessColor.BLACK))
    assert not ActionRules.can_submit(action, timelines)
    assert {board.timeline for board in ActionRules.required_boards(
        action,
        timelines,
    )} == {1}

    timelines[1].add_position(_position(1, 1, ChessColor.BLACK))
    assert ActionRules.can_submit(action, timelines)
    assert ActionRules.required_boards(action, timelines) == ()
    assert ActionRules.submit(action, timelines)
    assert action.submitted


def test_temporal_move_counts_as_playing_both_source_and_destination_boards():
    timelines = {
        0: _timeline(0, 0),
        1: _timeline(1, 0, ChessColor.WHITE),
    }
    rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    timelines[0].positions[0].set_piece(3, 3, rook)
    move = Move(
        piece=rook,
        source=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 3, 3),
        destination=Square5D(BoardCoord(1, 0, ChessColor.WHITE), 3, 3),
    )
    action = ActionRules.begin(ChessColor.WHITE, timelines)

    assert ActionRules.can_play_move(action, move, timelines)

    # Engine-level temporal execution advances both source and destination
    # timelines.  Model that state transition here and verify both obligations
    # disappear together.
    timelines[0].add_position(_position(0, 1, ChessColor.BLACK))
    timelines[1].add_position(_position(1, 1, ChessColor.BLACK))
    action.record(move)

    assert ActionRules.can_submit(action, timelines)


def test_action_rejects_opponent_or_historical_source_move():
    timelines = {0: _timeline(0, 2)}
    action = ActionRules.begin(ChessColor.WHITE, timelines)
    white_rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    black_rook = Piece(PieceType.ROOK, ChessColor.BLACK)

    historical = Move(
        piece=white_rook,
        source=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 0, 0),
        destination=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 0, 1),
    )
    opponent = Move(
        piece=black_rook,
        source=Square5D(BoardCoord(0, 1, ChessColor.WHITE), 0, 0),
        destination=Square5D(BoardCoord(0, 1, ChessColor.WHITE), 0, 1),
    )

    assert not ActionRules.can_play_move(action, historical, timelines)
    assert not ActionRules.can_play_move(action, opponent, timelines)
