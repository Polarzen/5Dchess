"""Focused tests for canonical non-pawn 4D move generation."""

from src.engine.board import Position
from src.engine.coordinates import BoardCoord, Vector4D
from src.engine.move_generator import MoveGenerator
from src.engine.timeline import Timeline
from src.utils.constants import ChessColor, PieceType


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


def timeline_with(*positions: Position, owner: ChessColor | None = None) -> Timeline:
    assert positions
    timeline = Timeline(positions[0].timeline_id, owner=owner)
    for position in positions:
        timeline.add_position(position)
    return timeline


def multiverse_moves(generator: MoveGenerator, piece_type: PieceType):
    return [
        move
        for move in generator.generate_all()
        if move.piece.piece_type == piece_type and not move.is_spatial
    ]


def test_rook_moves_purely_through_time_when_path_exists():
    target = make_position(0, 0, {(0, 0): "K"})
    middle = make_position(0, 2, {(0, 0): "K"})
    source = make_position(0, 4, {(0, 0): "K", (4, 4): "R"})
    timeline = timeline_with(target, middle, source)

    moves = multiverse_moves(MoveGenerator(source, {0: timeline}), PieceType.ROOK)
    move = next(
        move for move in moves
        if move.destination.board == BoardCoord(0, 0, ChessColor.WHITE)
        and (move.to_x, move.to_y) == (4, 4)
    )

    assert move.vector == Vector4D(0, 0, -2, 0)
    assert move.is_branching
    assert move.captured is None


def test_slider_does_not_cross_occupied_intermediate_4d_square():
    target = make_position(0, 0)
    middle = make_position(0, 2, {(4, 4): "P"})
    source = make_position(0, 4, {(4, 4): "R"})
    timeline = timeline_with(target, middle, source)

    moves = multiverse_moves(MoveGenerator(source, {0: timeline}), PieceType.ROOK)

    assert not any(
        move.destination.board == BoardCoord(0, 0, ChessColor.WHITE)
        and (move.to_x, move.to_y) == (4, 4)
        for move in moves
    )


def test_bishop_combines_space_and_time_and_can_capture():
    target = make_position(0, 0, {(6, 4): "p"})
    middle = make_position(0, 2)
    source = make_position(0, 4, {(4, 4): "B"})
    timeline = timeline_with(target, middle, source)

    moves = multiverse_moves(MoveGenerator(source, {0: timeline}), PieceType.BISHOP)
    move = next(
        move for move in moves
        if move.destination.board == BoardCoord(0, 0, ChessColor.WHITE)
        and (move.to_x, move.to_y) == (6, 4)
    )

    assert move.vector == Vector4D(2, 0, -2, 0)
    assert move.is_branching
    assert move.captured is not None
    assert move.captured.color == ChessColor.BLACK


def test_queen_combines_time_and_timeline_axes_with_path_resolution():
    source = make_position(0, 4, {(4, 4): "Q"})
    lane_zero = timeline_with(source)

    intermediate = make_position(1, 2)
    lane_one = timeline_with(intermediate, owner=ChessColor.WHITE)

    target = make_position(2, 0)
    lane_two = timeline_with(target, owner=ChessColor.WHITE)

    timelines = {0: lane_zero, 1: lane_one, 2: lane_two}
    moves = multiverse_moves(MoveGenerator(source, timelines), PieceType.QUEEN)
    move = next(
        move for move in moves
        if move.destination.board == BoardCoord(2, 0, ChessColor.WHITE)
        and (move.to_x, move.to_y) == (4, 4)
    )

    assert move.vector == Vector4D(0, 0, -2, 2)
    assert move.is_cross_timeline
    assert not move.is_branching  # lane L+2 target is its playable board


def test_king_can_move_one_step_through_time():
    target = make_position(0, 0, {(3, 4): "K"})
    source = make_position(0, 2, {(4, 4): "K"})
    timeline = timeline_with(target, source)

    moves = multiverse_moves(MoveGenerator(source, {0: timeline}), PieceType.KING)

    assert any(
        move.destination.board == BoardCoord(0, 0, ChessColor.WHITE)
        and (move.to_x, move.to_y) == (4, 4)
        and move.vector == Vector4D(0, 0, -1, 0)
        for move in moves
    )


def test_knight_can_jump_over_missing_intermediate_board():
    target = make_position(0, 0)
    source = make_position(0, 4, {(3, 3): "N"})
    # T1w is intentionally absent. Knight movement should not use PathRules.
    timeline = timeline_with(target, source)

    moves = multiverse_moves(MoveGenerator(source, {0: timeline}), PieceType.KNIGHT)

    assert any(
        move.destination.board == BoardCoord(0, 0, ChessColor.WHITE)
        and (move.to_x, move.to_y) == (4, 3)
        and move.vector == Vector4D(1, 0, -2, 0)
        for move in moves
    )


def test_pawn_has_no_multiverse_move_until_pawn_rules_are_implemented():
    target = make_position(0, 0)
    source = make_position(0, 2, {(4, 6): "P"})
    timeline = timeline_with(target, source)

    moves = multiverse_moves(MoveGenerator(source, {0: timeline}), PieceType.PAWN)

    assert moves == []


def test_historical_board_cannot_be_a_move_source():
    historical = make_position(0, 0, {(4, 4): "Q"})
    latest = make_position(0, 2)
    timeline = timeline_with(historical, latest)

    assert MoveGenerator(historical, {0: timeline}).generate_all() == []
