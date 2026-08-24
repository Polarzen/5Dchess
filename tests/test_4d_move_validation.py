"""Tests for board-local validation of canonical multiverse moves."""

from src.engine.board import Position
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.move_generator import Move
from src.engine.move_validator import MoveValidator
from src.engine.timeline import Timeline
from src.utils.constants import ChessColor


def make_position(
    timeline_id: int,
    time_point: int,
    pieces: dict[tuple[int, int], str] | None = None,
) -> Position:
    board = [["" for _ in range(8)] for _ in range(8)]
    for (x, y), piece in (pieces or {}).items():
        board[y][x] = piece
    return Position(
        board=board,
        turn=BoardCoord.legacy_side_for_time_point(time_point),
        timeline_id=timeline_id,
        time_point=time_point,
    )


def timeline_with(*positions: Position) -> Timeline:
    timeline = Timeline(positions[0].timeline_id)
    for position in positions:
        timeline.add_position(position)
    return timeline


def square(position: Position, x: int, y: int) -> Square5D:
    return Square5D(
        BoardCoord.from_legacy_time_point(
            position.timeline_id,
            position.time_point,
            position.turn,
        ),
        x,
        y,
    )


def test_valid_time_move_checks_source_and_destination_separately():
    target = make_position(0, 0, {(0, 7): "K"})
    source = make_position(0, 2, {(0, 7): "K", (4, 4): "R"})
    timeline = timeline_with(target, source)
    rook = source.get_piece(4, 4)
    move = Move(
        piece=rook,
        source=square(source, 4, 4),
        destination=square(target, 4, 4),
        is_branching=True,
    )

    validator = MoveValidator({0: timeline})

    assert validator.filter_legal_moves(source, [move]) == [move]


def test_time_move_rejected_when_leaving_source_king_exposed():
    target = make_position(0, 0, {(0, 7): "K"})
    source = make_position(
        0,
        2,
        {
            (4, 7): "K",
            (4, 4): "R",  # blocks the black rook before travelling
            (4, 0): "r",
        },
    )
    timeline = timeline_with(target, source)
    move = Move(
        piece=source.get_piece(4, 4),
        source=square(source, 4, 4),
        destination=square(target, 4, 4),
        is_branching=True,
    )

    validator = MoveValidator({0: timeline})

    assert validator.filter_legal_moves(source, [move]) == []


def test_king_time_move_rejected_when_destination_is_attacked():
    target = make_position(0, 0, {(4, 0): "r"})
    source = make_position(0, 2, {(4, 4): "K"})
    timeline = timeline_with(target, source)
    move = Move(
        piece=source.get_piece(4, 4),
        source=square(source, 4, 4),
        destination=square(target, 4, 4),
        is_branching=True,
    )

    validator = MoveValidator({0: timeline})

    assert validator.filter_legal_moves(source, [move]) == []


def test_manual_slider_move_rejected_when_4d_path_is_blocked():
    target = make_position(0, 0, {(0, 7): "K"})
    middle = make_position(0, 2, {(4, 4): "P", (0, 7): "K"})
    source = make_position(0, 4, {(4, 4): "R", (0, 7): "K"})
    timeline = timeline_with(target, middle, source)
    move = Move(
        piece=source.get_piece(4, 4),
        source=square(source, 4, 4),
        destination=square(target, 4, 4),
        is_branching=True,
    )

    validator = MoveValidator({0: timeline})

    assert validator.filter_legal_moves(source, [move]) == []


def test_historical_target_requires_branching_metadata():
    target = make_position(0, 0, {(0, 7): "K"})
    source = make_position(0, 2, {(0, 7): "K", (4, 4): "R"})
    timeline = timeline_with(target, source)
    move = Move(
        piece=source.get_piece(4, 4),
        source=square(source, 4, 4),
        destination=square(target, 4, 4),
        is_branching=False,
    )

    validator = MoveValidator({0: timeline})

    assert validator.filter_legal_moves(source, [move]) == []


def test_friendly_piece_on_destination_board_blocks_move():
    target = make_position(0, 0, {(0, 7): "K", (4, 4): "N"})
    source = make_position(0, 2, {(0, 7): "K", (4, 4): "R"})
    timeline = timeline_with(target, source)
    move = Move(
        piece=source.get_piece(4, 4),
        source=square(source, 4, 4),
        destination=square(target, 4, 4),
        captured=target.get_piece(4, 4),
        is_branching=True,
    )

    validator = MoveValidator({0: timeline})

    assert validator.filter_legal_moves(source, [move]) == []


def test_cross_timeline_move_to_playable_board_does_not_branch():
    source = make_position(0, 0, {(0, 7): "K", (4, 4): "R"})
    target = make_position(1, 0, {(0, 7): "K"})
    source_timeline = timeline_with(source)
    target_timeline = timeline_with(target)
    move = Move(
        piece=source.get_piece(4, 4),
        source=square(source, 4, 4),
        destination=square(target, 4, 4),
        is_branching=False,
    )

    validator = MoveValidator({0: source_timeline, 1: target_timeline})

    assert move.is_cross_timeline
    assert validator.filter_legal_moves(source, [move]) == [move]


def test_pawn_multiverse_move_is_rejected_until_pawn_rules_exist():
    target = make_position(0, 0, {(0, 7): "K"})
    source = make_position(0, 2, {(0, 7): "K", (4, 6): "P"})
    timeline = timeline_with(target, source)
    move = Move(
        piece=source.get_piece(4, 6),
        source=square(source, 4, 6),
        destination=square(target, 4, 6),
        is_branching=True,
    )

    validator = MoveValidator({0: timeline})

    assert validator.filter_legal_moves(source, [move]) == []
