"""Canonical state-transition tests for FiveDEngine execution."""

import inspect

from src.engine import FiveDEngine, Move, Position, Timeline
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.piece import Piece
from src.utils.constants import ChessColor, PieceType


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
        unmoved_pawns=unmoved_pawns,
    )


def _timeline(timeline_id: int, *positions: Position) -> Timeline:
    timeline = Timeline(timeline_id=timeline_id)
    for position in positions:
        timeline.add_position(position)
    return timeline


def test_engine_resolves_boardcoord_at_legacy_storage_boundary():
    engine = FiveDEngine()
    main = engine.timeline_manager.get_timeline(0)
    main.positions.clear()
    position = _position(0, 2, ChessColor.WHITE)
    main.add_position(position)

    coord = BoardCoord(timeline=0, turn=1, side=ChessColor.WHITE)
    assert coord.legacy_time_point == 2
    assert engine._resolve_position(coord) is position


def test_spatial_execution_uses_canonical_squares_and_advances_half_move():
    engine = FiveDEngine()
    move = next(
        move
        for move in engine.get_legal_moves()
        if move.source.x == 4
        and move.source.y == 6
        and move.destination.x == 4
        and move.destination.y == 4
    )
    source_board = move.source.board

    assert engine.execute_move(move)

    main = engine.timeline_manager.get_timeline(0)
    assert main.positions[source_board.legacy_time_point].get_piece(4, 6) == move.piece

    successor_coord = source_board.next()
    successor = engine._resolve_position(successor_coord)
    assert successor is not None
    assert successor.time_point == successor_coord.legacy_time_point == 1
    assert successor.get_piece(4, 6) is None
    assert successor.get_piece(4, 4) == move.piece
    assert not successor.is_pawn_unmoved(4, 4)
    assert successor.en_passant_target == (4, 5)


def test_spatial_promotion_is_applied_on_successor_only():
    engine = FiveDEngine()
    main = engine.timeline_manager.get_timeline(0)
    main.positions.clear()

    pawn = Piece(PieceType.PAWN, ChessColor.WHITE)
    source_position = _position(
        0,
        0,
        ChessColor.WHITE,
        (0, 1, "P"),
        unmoved_pawns=set(),
    )
    main.add_position(source_position)

    move = Move(
        piece=pawn,
        source=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 0, 1),
        destination=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 0, 0),
        promotion=PieceType.QUEEN,
    )

    assert engine.execute_move(move)
    assert main.positions[0].get_piece(0, 1) == pawn
    promoted = main.positions[1].get_piece(0, 0)
    assert promoted == Piece(PieceType.QUEEN, ChessColor.WHITE)
    assert not main.positions[1].is_pawn_unmoved(0, 0)


def test_normal_move_rejects_historical_source_board():
    engine = FiveDEngine()
    main = engine.timeline_manager.get_timeline(0)
    main.positions.clear()

    rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    old = _position(0, 0, ChessColor.WHITE, (3, 3, "R"))
    latest = _position(0, 2, ChessColor.WHITE, (3, 3, "R"))
    main.add_position(old)
    main.add_position(latest)

    move = Move(
        piece=rook,
        source=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 3, 3),
        destination=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 3, 4),
    )

    assert not engine.execute_move(move)
    assert 1 not in main.positions


def test_branching_uses_canonical_source_not_active_timeline_and_keeps_history_immutable():
    engine = FiveDEngine()
    manager = engine.timeline_manager
    main = manager.get_timeline(0)
    main.positions.clear()

    captured = Piece(PieceType.ROOK, ChessColor.BLACK)
    destination_past = _position(0, 0, ChessColor.WHITE, (4, 4, "r"))
    destination_latest = _position(0, 2, ChessColor.WHITE)
    main.add_position(destination_past)
    main.add_position(destination_latest)

    queen = Piece(PieceType.QUEEN, ChessColor.WHITE)
    source_position = _position(1, 2, ChessColor.WHITE, (4, 4, "Q"))
    source_timeline = _timeline(1, source_position)
    manager.timelines[1] = source_timeline
    manager.active_timeline_id = 0

    move = Move(
        piece=queen,
        source=Square5D(BoardCoord(1, 1, ChessColor.WHITE), 4, 4),
        destination=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 4, 4),
        captured=captured,
        is_branching=True,
    )

    assert engine.execute_move(move)

    branch = manager.get_timeline(2)
    assert branch is not None
    assert branch.parent_id == 0
    assert branch.branch_turn == move.source.board.legacy_time_point
    assert engine.move_history[-1].created_timeline == 2
    assert manager.active_timeline_id == 2

    # Original source and destination histories are immutable.
    assert source_timeline.positions[2].get_piece(4, 4) == queen
    assert main.positions[0].get_piece(4, 4) == captured

    # Successors carry departure and arrival/capture.
    assert source_timeline.positions[3].get_piece(4, 4) is None
    assert branch.positions[1].get_piece(4, 4) == queen


def test_branching_requires_a_historical_destination():
    engine = FiveDEngine()
    main = engine.timeline_manager.get_timeline(0)
    main.positions.clear()

    rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    playable = _position(0, 0, ChessColor.WHITE, (3, 3, "R"))
    main.add_position(playable)

    move = Move(
        piece=rook,
        source=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 3, 3),
        destination=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 3, 4),
        is_branching=True,
    )

    assert not engine.execute_move(move)
    assert len(engine.timeline_manager.timelines) == 1


def test_cross_timeline_execution_does_not_guess_source_from_active_timeline():
    engine = FiveDEngine()
    manager = engine.timeline_manager
    main = manager.get_timeline(0)
    main.positions.clear()

    target_position = _position(0, 0, ChessColor.WHITE)
    main.add_position(target_position)

    rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    source_position = _position(1, 0, ChessColor.WHITE, (3, 3, "R"))
    source_timeline = _timeline(1, source_position)
    manager.timelines[1] = source_timeline
    manager.active_timeline_id = 0

    move = Move(
        piece=rook,
        source=Square5D(BoardCoord(1, 0, ChessColor.WHITE), 3, 3),
        destination=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 3, 3),
    )

    assert engine.execute_move(move)

    assert source_timeline.positions[0].get_piece(3, 3) == rook
    assert main.positions[0].get_piece(3, 3) is None
    assert source_timeline.positions[1].get_piece(3, 3) is None
    assert main.positions[1].get_piece(3, 3) == rook


def test_cross_timeline_destination_must_be_playable():
    engine = FiveDEngine()
    manager = engine.timeline_manager
    main = manager.get_timeline(0)
    main.positions.clear()

    target_past = _position(0, 0, ChessColor.WHITE)
    target_latest = _position(0, 2, ChessColor.WHITE)
    main.add_position(target_past)
    main.add_position(target_latest)

    rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    source_position = _position(1, 2, ChessColor.WHITE, (3, 3, "R"))
    source_timeline = _timeline(1, source_position)
    manager.timelines[1] = source_timeline

    move = Move(
        piece=rook,
        source=Square5D(BoardCoord(1, 1, ChessColor.WHITE), 3, 3),
        destination=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 3, 3),
    )

    assert not engine.execute_move(move)
    assert 3 not in source_timeline.positions
    assert 1 not in main.positions


def test_cross_timeline_pawn_is_marked_moved_on_both_successors():
    engine = FiveDEngine()
    manager = engine.timeline_manager
    main = manager.get_timeline(0)
    main.positions.clear()

    pawn = Piece(PieceType.PAWN, ChessColor.WHITE)
    source_position = _position(
        0,
        4,
        ChessColor.WHITE,
        (4, 6, "P"),
        unmoved_pawns={(4, 6)},
    )
    main.add_position(source_position)

    target_position = _position(-1, 4, ChessColor.WHITE)
    target_timeline = _timeline(-1, target_position)
    manager.timelines[-1] = target_timeline

    move = Move(
        piece=pawn,
        source=Square5D(BoardCoord(0, 2, ChessColor.WHITE), 4, 6),
        destination=Square5D(BoardCoord(-1, 2, ChessColor.WHITE), 4, 6),
    )

    assert engine.execute_move(move)

    source_after = main.positions[5]
    target_after = target_timeline.positions[5]
    assert source_after.get_piece(4, 6) is None
    assert (4, 6) not in source_after.unmoved_pawns
    assert target_after.get_piece(4, 6) == pawn
    assert not target_after.is_pawn_unmoved(4, 6)
    assert target_after.en_passant_target is None


def test_execution_layer_no_longer_reads_legacy_move_accessors():
    execution_source = "\n".join(
        inspect.getsource(method)
        for method in (
            FiveDEngine._execute_normal_move,
            FiveDEngine._execute_branching_move,
            FiveDEngine._execute_cross_timeline_move,
            FiveDEngine._update_castling_rights,
        )
    )

    for accessor in (
        ".from_time",
        ".to_time",
        ".from_timeline_id",
        ".to_timeline_id",
        ".from_x",
        ".from_y",
        ".to_x",
        ".to_y",
    ):
        assert accessor not in execution_source
