"""Integration tests for branch/cross-timeline execution invariants."""

from src.engine import FiveDEngine, Move, Position, Timeline
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.piece import Piece
from src.utils.constants import ChessColor, PieceType


def empty_position(timeline_id: int, time_point: int, side: ChessColor) -> Position:
    board = [["" for _ in range(8)] for _ in range(8)]
    board[7][4] = "K"
    board[0][4] = "k"
    return Position(
        board=board,
        turn=side,
        timeline_id=timeline_id,
        time_point=time_point,
    )


def test_branch_execution_uses_destination_parent_and_records_created_lane():
    engine = FiveDEngine()
    main = engine.timeline_manager.get_timeline(0)

    # Build a consistent T0w -> T0b -> T1w history on L0.
    main.positions.clear()
    p0 = empty_position(0, 0, ChessColor.WHITE)
    p1 = empty_position(0, 1, ChessColor.BLACK)
    p2 = empty_position(0, 2, ChessColor.WHITE)
    rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    p2.set_piece(3, 4, rook)
    for position in (p0, p1, p2):
        main.add_position(position)

    move = Move(
        piece=rook,
        source=Square5D(BoardCoord(0, 1, ChessColor.WHITE), 3, 4),
        destination=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 3, 4),
        is_branching=True,
    )

    assert engine.execute_move(move)

    branch = engine.timeline_manager.get_timeline(1)
    assert branch is not None
    assert branch.parent_id == 0
    assert branch.owner == ChessColor.WHITE
    assert engine.move_history[-1].created_timeline == 1
    assert engine.timeline_manager.active_timeline_id == 1

    # Stored source history is immutable; its successor carries the removal.
    assert main.positions[2].get_piece(3, 4) == rook
    assert main.positions[3].get_piece(3, 4) is None
    # The branch successor carries the arriving rook.
    assert branch.positions[1].get_piece(3, 4) == rook


def test_cross_timeline_execution_never_mutates_stored_source_or_target_boards():
    engine = FiveDEngine()
    manager = engine.timeline_manager
    main = manager.get_timeline(0)
    main.positions.clear()

    rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    source = empty_position(0, 0, ChessColor.WHITE)
    source.set_piece(3, 3, rook)
    main.add_position(source)

    target_timeline = Timeline(timeline_id=1, parent_id=0, owner=ChessColor.WHITE)
    target = empty_position(1, 0, ChessColor.WHITE)
    target_timeline.add_position(target)
    manager.timelines[1] = target_timeline
    manager.active_timeline_id = 0

    move = Move(
        piece=rook,
        source=Square5D(BoardCoord(0, 0, ChessColor.WHITE), 3, 3),
        destination=Square5D(BoardCoord(1, 0, ChessColor.WHITE), 3, 3),
    )

    assert engine.execute_move(move)

    # Historical input boards remain untouched.
    assert main.positions[0].get_piece(3, 3) == rook
    assert target_timeline.positions[0].get_piece(3, 3) is None

    # Both playable timelines advance independently.
    assert main.positions[1].get_piece(3, 3) is None
    assert target_timeline.positions[1].get_piece(3, 3) == rook
    assert main.positions[1].turn == ChessColor.BLACK
    assert target_timeline.positions[1].turn == ChessColor.BLACK
