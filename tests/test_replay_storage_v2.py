"""Regression coverage for canonical Replay / Storage v2."""
from __future__ import annotations

import json

from src.data.archive import GameArchive, move_from_dict, move_to_dict
from src.data.models import ActionRecord, MoveRecord
from src.data.pgn_parser import FiveDPGN
from src.engine import ActionRules, BoardCoord, FiveDEngine, Move, Piece, Position, Square5D, Timeline
from src.modes.replay import ReplayMode
from src.utils.constants import ChessColor, PieceType


def _empty_position(timeline_id: int, time_point: int, side: ChessColor) -> Position:
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


def _two_move_action_engine() -> FiveDEngine:
    engine = FiveDEngine()
    manager = engine.timeline_manager
    main = manager.get_timeline(0)
    main.positions.clear()

    rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    present = _empty_position(0, 0, ChessColor.WHITE)
    present.set_piece(0, 6, rook)
    main.add_position(present)

    future = _timeline_through(1, 2, owner=ChessColor.WHITE)
    future.positions[2].set_piece(1, 6, rook)
    manager.timelines[1] = future
    manager.refresh_activity()
    engine.current_turn_color = ChessColor.WHITE
    engine.action_history = []
    engine.current_action = ActionRules.begin(ChessColor.WHITE, manager.timelines)
    GameArchive.set_replay_origin(engine)

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
    assert engine.execute_action_move(optional_future)
    assert engine.can_submit_action()
    assert engine.submit_action()
    return engine


def test_move_storage_uses_canonical_board_coords():
    rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    move = Move(
        piece=rook,
        source=Square5D(BoardCoord(-1, 3, ChessColor.WHITE), 2, 3),
        destination=Square5D(BoardCoord(2, 1, ChessColor.WHITE), 2, 3),
        is_branching=False,
    )
    data = move_to_dict(move)

    assert data["source"]["board"] == {
        "timeline": -1,
        "turn": 3,
        "side": "white",
        "time_point": 6,
    }
    assert data["destination"]["board"]["timeline"] == 2
    assert "from_x" not in data
    assert move_from_dict(data) == move


def test_archive_roundtrip_preserves_action_submit_boundary_and_state():
    engine = _two_move_action_engine()
    archive = GameArchive.capture(engine)
    restored = GameArchive.restore(archive)

    assert archive["schema_version"] == 2
    assert "replay_origin" in archive
    assert len(restored.action_history) == 1
    assert restored.action_history[0].submitted
    assert len(restored.action_history[0].moves) == 2
    assert restored.current_turn_color == ChessColor.BLACK
    assert GameArchive.capture(restored) == archive


def test_5dpgn_v2_roundtrip_is_exact(tmp_path):
    engine = _two_move_action_engine()
    filepath = tmp_path / "action-aware.5dpgn"

    assert FiveDPGN.save(str(filepath), engine, {"mode": "pvp"})
    raw = json.loads(filepath.read_text(encoding="utf-8"))
    assert raw["metadata"]["version"] == "2.0"
    assert raw["game"]["schema_version"] == 2
    assert "replay_origin" in raw["game"]
    assert len(raw["game"]["action_history"]) == 1
    stored_move = raw["game"]["action_history"][0]["moves"][0]
    assert "source" in stored_move and "destination" in stored_move
    assert "from_time" not in stored_move

    loaded = FiveDPGN.load_engine(str(filepath))
    assert loaded is not None
    assert GameArchive.capture(loaded) == GameArchive.capture(engine)


def test_replay_steps_moves_but_submits_only_at_recorded_action_end():
    final_engine = _two_move_action_engine()
    replay = ReplayMode()
    replay.load_from_engine(final_engine)
    replay.start()

    assert replay.current_index == 0
    assert replay.engine.current_turn_color == ChessColor.WHITE

    assert replay.step_forward()
    assert replay.current_index == 1
    assert replay.engine.current_turn_color == ChessColor.WHITE
    assert len(replay.engine.current_action.moves) == 1

    assert replay.step_forward()
    assert replay.current_index == 2
    assert replay.engine.current_turn_color == ChessColor.BLACK
    assert len(replay.engine.action_history) == 1
    assert len(replay.engine.action_history[0].moves) == 2

    replay.step_backward()
    assert replay.engine.current_turn_color == ChessColor.WHITE
    replay.jump_to_end()
    assert GameArchive.capture(replay.engine) == GameArchive.capture(final_engine)


def test_legacy_v1_file_remains_readable(tmp_path):
    engine = FiveDEngine()
    move = next(
        item for item in engine.get_legal_moves()
        if item.from_x == 4 and item.from_y == 6 and item.to_y == 4
    )
    assert engine.execute_move(move)
    recorded = engine.move_history[0]
    legacy_game = {
        "max_timelines": engine.max_timelines,
        "max_turns": engine.max_turns,
        "timeline_manager": engine.timeline_manager.to_dict(),
        "game_state": engine.game_state.name,
        "move_history": [{
            "piece_type": recorded.piece.piece_type.value,
            "piece_color": recorded.piece.color.value,
            "from_x": recorded.from_x,
            "from_y": recorded.from_y,
            "to_x": recorded.to_x,
            "to_y": recorded.to_y,
            "from_timeline_id": recorded.from_timeline_id,
            "to_timeline_id": recorded.to_timeline_id,
            "from_time": recorded.from_time,
            "to_time": recorded.to_time,
            "is_branching": recorded.is_branching,
            "created_timeline": recorded.created_timeline,
            "is_castling": recorded.is_castling,
            "is_en_passant": recorded.is_en_passant,
            "promotion": None,
            "captured": None,
        }],
        "move_counter": 1,
        "current_turn_color": "black",
    }
    filepath = tmp_path / "legacy.5dpgn"
    filepath.write_text(
        json.dumps({
            "metadata": {"format": "5dpgn", "version": "1.0"},
            "game": legacy_game,
        }),
        encoding="utf-8",
    )

    loaded = FiveDPGN.load_engine(str(filepath))
    assert loaded is not None
    assert len(loaded.move_history) == 1
    assert loaded.move_history[0].source == recorded.source
    assert loaded.current_turn_color == ChessColor.BLACK


def test_database_records_keep_signed_lane_and_action_identity():
    engine = _two_move_action_engine()
    action = engine.action_history[0]
    action_record = ActionRecord.from_action(action, game_id=7, action_index=0)
    move_record = MoveRecord.from_move(
        action.moves[1],
        game_id=7,
        action_index=0,
        move_index=1,
    )

    assert action_record.submitted
    assert action_record.move_count == 2
    assert move_record.source_timeline == 1
    assert move_record.source_turn == 1
    assert move_record.source_side == "white"
    assert move_record.action_index == 0
    assert move_record.move_index == 1
    assert move_record.from_time == 2
