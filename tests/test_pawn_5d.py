from src.engine import FiveDEngine, MoveGenerator, MoveValidator, Position, Timeline
from src.utils.constants import ChessColor, PieceType


def _board(*pieces):
    board = [["" for _ in range(8)] for _ in range(8)]
    for x, y, char in pieces:
        board[y][x] = char
    return board


def _position(timeline_id, time_point, turn, *pieces, unmoved_pawns=None):
    return Position(
        board=_board(*pieces),
        turn=turn,
        timeline_id=timeline_id,
        time_point=time_point,
        unmoved_pawns=unmoved_pawns,
    )


def _timeline(timeline_id, *positions):
    timeline = Timeline(timeline_id=timeline_id)
    for position in positions:
        timeline.add_position(position)
    return timeline


def _pawn_moves(position, timelines):
    return [
        move
        for move in MoveGenerator(position, timelines).generate_all()
        if move.piece.piece_type == PieceType.PAWN
    ]


def test_white_pawn_advances_one_timeline_toward_negative_l():
    source = _position(
        0, 4, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"), (4, 6, "P"),
    )
    target = _position(
        -1, 4, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"),
    )
    timelines = {
        0: _timeline(0, source),
        -1: _timeline(-1, target),
    }

    moves = _pawn_moves(source, timelines)
    match = [m for m in moves if m.to_timeline_id == -1 and m.to_time == 4]

    assert len(match) == 1
    assert match[0].to_x == 4 and match[0].to_y == 6
    assert match[0].captured is None
    assert not match[0].is_branching
    assert MoveValidator(timelines).filter_legal_moves(source, match) == match


def test_black_pawn_advances_one_timeline_toward_positive_l():
    source = _position(
        0, 5, ChessColor.BLACK,
        (0, 7, "K"), (7, 0, "k"), (4, 1, "p"),
    )
    target = _position(
        1, 5, ChessColor.BLACK,
        (0, 7, "K"), (7, 0, "k"),
    )
    timelines = {
        0: _timeline(0, source),
        1: _timeline(1, target),
    }

    moves = _pawn_moves(source, timelines)
    assert any(m.to_timeline_id == 1 and m.to_time == 5 for m in moves)
    assert not any(m.to_timeline_id == -1 for m in moves)


def test_pawn_temporal_capture_uses_t_and_l_pair():
    source = _position(
        0, 4, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"), (4, 6, "P"),
    )
    target = _position(
        -1, 2, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"), (4, 6, "p"),
    )
    timelines = {
        0: _timeline(0, source),
        -1: _timeline(-1, target),
    }

    moves = _pawn_moves(source, timelines)
    captures = [
        m for m in moves
        if m.to_timeline_id == -1 and m.to_time == 2 and m.captured is not None
    ]

    assert len(captures) == 1
    assert captures[0].vector.dt == -1
    assert captures[0].vector.dl == -1
    assert MoveValidator(timelines).filter_legal_moves(source, captures) == captures


def test_temporal_capture_requires_enemy_on_destination():
    source = _position(
        0, 4, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"), (4, 6, "P"),
    )
    empty_diagonal = _position(
        -1, 2, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"),
    )
    timelines = {
        0: _timeline(0, source),
        -1: _timeline(-1, empty_diagonal),
    }

    moves = _pawn_moves(source, timelines)
    assert not any(m.to_timeline_id == -1 and m.to_time == 2 for m in moves)


def test_first_move_can_advance_two_timelines_through_clear_intermediate_board():
    source = _position(
        0, 4, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"), (4, 6, "P"),
    )
    middle = _position(
        -1, 4, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"),
    )
    target = _position(
        -2, 4, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"),
    )
    timelines = {
        0: _timeline(0, source),
        -1: _timeline(-1, middle),
        -2: _timeline(-2, target),
    }

    moves = _pawn_moves(source, timelines)
    doubles = [m for m in moves if m.to_timeline_id == -2 and m.to_time == 4]

    assert len(doubles) == 1
    assert MoveValidator(timelines).filter_legal_moves(source, doubles) == doubles


def test_timeline_double_is_blocked_by_missing_or_occupied_intermediate_board():
    source = _position(
        0, 4, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"), (4, 6, "P"),
    )
    target = _position(
        -2, 4, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"),
    )
    missing = {
        0: _timeline(0, source),
        -2: _timeline(-2, target),
    }
    assert not any(m.to_timeline_id == -2 for m in _pawn_moves(source, missing))

    blocked_middle = _position(
        -1, 4, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"), (4, 6, "n"),
    )
    blocked = {
        0: _timeline(0, source),
        -1: _timeline(-1, blocked_middle),
        -2: _timeline(-2, target),
    }
    assert not any(m.to_timeline_id == -2 for m in _pawn_moves(source, blocked))


def test_moved_pawn_cannot_use_timeline_double_again():
    source = _position(
        0, 4, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"), (4, 6, "P"),
        unmoved_pawns=set(),
    )
    middle = _position(-1, 4, ChessColor.WHITE, (0, 7, "K"), (7, 0, "k"))
    target = _position(-2, 4, ChessColor.WHITE, (0, 7, "K"), (7, 0, "k"))
    timelines = {
        0: _timeline(0, source),
        -1: _timeline(-1, middle),
        -2: _timeline(-2, target),
    }

    moves = _pawn_moves(source, timelines)
    assert any(m.to_timeline_id == -1 for m in moves)
    assert not any(m.to_timeline_id == -2 for m in moves)


def test_historical_temporal_capture_is_marked_branching():
    source = _position(
        0, 4, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"), (4, 6, "P"),
    )
    past = _position(
        -1, 2, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"), (4, 6, "p"),
    )
    later = _position(
        -1, 4, ChessColor.WHITE,
        (0, 7, "K"), (7, 0, "k"),
    )
    timelines = {
        0: _timeline(0, source),
        -1: _timeline(-1, past, later),
    }

    move = next(
        m for m in _pawn_moves(source, timelines)
        if m.to_timeline_id == -1 and m.to_time == 2
    )
    assert move.is_branching


def test_position_tracks_and_serializes_pawn_first_move_state():
    position = Position.initial()
    assert position.is_pawn_unmoved(4, 6)

    position.move_piece(4, 6, 4, 5)
    assert not position.is_pawn_unmoved(4, 5)

    restored = Position.from_dict(position.to_dict())
    assert not restored.is_pawn_unmoved(4, 5)


def test_old_position_data_infers_unmoved_starting_pawns():
    data = Position.initial().to_dict()
    data.pop("unmoved_pawns")

    restored = Position.from_dict(data)
    assert restored.is_pawn_unmoved(4, 6)


def test_engine_sets_and_expires_same_board_en_passant_target():
    engine = FiveDEngine()
    white_double = next(
        m for m in engine.get_legal_moves()
        if m.from_x == 4 and m.from_y == 6 and m.to_x == 4 and m.to_y == 4
    )
    assert engine.execute_move(white_double)

    after_white = engine.get_current_position()
    assert after_white.en_passant_target == (4, 5)
    assert not after_white.is_pawn_unmoved(4, 4)

    black_one = next(
        m for m in engine.get_legal_moves()
        if m.from_x == 4 and m.from_y == 1 and m.to_x == 4 and m.to_y == 2
    )
    assert engine.execute_move(black_one)
    assert engine.get_current_position().en_passant_target is None
