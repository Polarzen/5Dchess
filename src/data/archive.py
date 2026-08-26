"""Canonical replay/storage archive helpers for 5D Chess.

The storage boundary owns serialization. Engine rules keep using BoardCoord,
Square5D, Move and Action directly; files/databases convert those objects to a
stable JSON-friendly schema here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.engine.action import Action, ActionRules
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.engine import FiveDEngine
from src.engine.move_generator import Move
from src.engine.piece import Piece
from src.engine.timeline import TimelineManager
from src.engine.timeline_rules import PresentState
from src.utils.constants import ChessColor, GameState, PieceType


ARCHIVE_SCHEMA_VERSION = 2


def board_coord_to_dict(coord: BoardCoord) -> dict[str, Any]:
    return {
        "timeline": coord.timeline,
        "turn": coord.turn,
        "side": coord.side.value,
        "time_point": coord.legacy_time_point,
    }


def board_coord_from_dict(data: dict[str, Any]) -> BoardCoord:
    timeline = int(data["timeline"])
    side = ChessColor(data["side"])
    if "turn" in data:
        return BoardCoord(timeline=timeline, turn=int(data["turn"]), side=side)
    return BoardCoord.from_legacy_time_point(
        timeline=timeline,
        time_point=int(data["time_point"]),
        side=side,
    )


def square_to_dict(square: Square5D) -> dict[str, Any]:
    return {"board": board_coord_to_dict(square.board), "x": square.x, "y": square.y}


def square_from_dict(data: dict[str, Any]) -> Square5D:
    return Square5D(
        board=board_coord_from_dict(data["board"]),
        x=int(data["x"]),
        y=int(data["y"]),
    )


def piece_to_dict(piece: Piece | None) -> dict[str, str] | None:
    if piece is None:
        return None
    return {"type": piece.piece_type.value, "color": piece.color.value}


def piece_from_dict(data: dict[str, Any] | None) -> Piece | None:
    if not data:
        return None
    return Piece(PieceType(data["type"]), ChessColor(data["color"]))


def move_to_dict(move: Move) -> dict[str, Any]:
    return {
        "piece": piece_to_dict(move.piece),
        "source": square_to_dict(move.source),
        "destination": square_to_dict(move.destination),
        "captured": piece_to_dict(move.captured),
        "promotion": move.promotion.value if move.promotion else None,
        "is_castling": move.is_castling,
        "is_en_passant": move.is_en_passant,
        "is_branching": move.is_branching,
        "created_timeline": move.created_timeline,
        "notation": move.to_notation(),
    }


def move_from_dict(data: dict[str, Any]) -> Move:
    piece = piece_from_dict(data["piece"])
    if piece is None:
        raise ValueError("stored Move is missing piece")
    promotion = data.get("promotion")
    return Move(
        piece=piece,
        source=square_from_dict(data["source"]),
        destination=square_from_dict(data["destination"]),
        captured=piece_from_dict(data.get("captured")),
        promotion=PieceType(promotion) if promotion else None,
        is_castling=bool(data.get("is_castling", False)),
        is_en_passant=bool(data.get("is_en_passant", False)),
        is_branching=bool(data.get("is_branching", False)),
        created_timeline=data.get("created_timeline"),
    )


def legacy_move_from_dict(data: dict[str, Any]) -> Move:
    """Read the v1 half-move based Move representation."""
    piece = Piece(PieceType(data["piece_type"]), ChessColor(data["piece_color"]))
    captured = None
    if data.get("captured"):
        captured = Piece(PieceType(data["captured"]), piece.color.opposite())
    promotion = PieceType(data["promotion"]) if data.get("promotion") else None
    source_board = BoardCoord.from_legacy_time_point(
        timeline=int(data["from_timeline_id"]),
        time_point=int(data["from_time"]),
        side=piece.color,
    )
    destination_board = BoardCoord.from_legacy_time_point(
        timeline=int(data["to_timeline_id"]),
        time_point=int(data["to_time"]),
        side=piece.color,
    )
    return Move(
        piece=piece,
        source=Square5D(source_board, int(data["from_x"]), int(data["from_y"])),
        destination=Square5D(destination_board, int(data["to_x"]), int(data["to_y"])),
        captured=captured,
        promotion=promotion,
        is_castling=bool(data.get("is_castling", False)),
        is_en_passant=bool(data.get("is_en_passant", False)),
        is_branching=bool(data.get("is_branching", False)),
        created_timeline=data.get("created_timeline"),
    )


def present_to_dict(present: PresentState | None) -> dict[str, Any] | None:
    if present is None:
        return None
    return {
        "legacy_time_point": present.legacy_time_point,
        "turn": present.turn,
        "side": present.side.value,
        "boards": [board_coord_to_dict(coord) for coord in present.boards],
    }


def present_from_dict(data: dict[str, Any] | None) -> PresentState | None:
    if not data:
        return None
    boards = tuple(board_coord_from_dict(item) for item in data.get("boards", []))
    side = ChessColor(data["side"])
    if boards:
        turn = boards[0].turn
        time_point = boards[0].legacy_time_point
    else:
        turn = int(data["turn"])
        time_point = int(data["legacy_time_point"])
    return PresentState(
        legacy_time_point=time_point,
        turn=turn,
        side=side,
        boards=boards,
    )


def action_to_dict(action: Action) -> dict[str, Any]:
    return {
        "color": action.color.value,
        "starting_present": present_to_dict(action.starting_present),
        "moves": [move_to_dict(move) for move in action.moves],
        "submitted": action.submitted,
    }


def action_from_dict(data: dict[str, Any]) -> Action:
    action = Action(
        color=ChessColor(data["color"]),
        starting_present=present_from_dict(data.get("starting_present")),
        moves=[],
        submitted=False,
    )
    for move_data in data.get("moves", []):
        action.record(move_from_dict(move_data))
    action.submitted = bool(data.get("submitted", False))
    return action


@dataclass(frozen=True, slots=True)
class ArchivePayload:
    engine: FiveDEngine
    metadata: dict[str, Any]
    schema_version: int


class GameArchive:
    """Capture/restore exact engine state plus the multiverse replay origin."""

    @staticmethod
    def capture_origin(engine: FiveDEngine) -> dict[str, Any]:
        """Capture the state from which replay Move history must begin."""
        return {
            "max_timelines": engine.max_timelines,
            "max_turns": engine.max_turns,
            "timeline_manager": engine.timeline_manager.to_dict(),
            "game_state": engine.game_state.name,
            "current_turn_color": engine.current_turn_color.value,
        }

    @classmethod
    def set_replay_origin(cls, engine: FiveDEngine) -> dict[str, Any]:
        """Mark the current no-history position as a custom replay starting point."""
        if engine.move_history or engine.action_history:
            raise ValueError("replay origin must be marked before recording Moves")
        origin = cls.capture_origin(engine)
        engine._replay_origin = origin
        return origin

    @classmethod
    def default_origin(cls, max_timelines: int = 32, max_turns: int = 500) -> dict[str, Any]:
        standard = FiveDEngine(max_timelines=max_timelines, max_turns=max_turns)
        return cls.capture_origin(standard)

    @classmethod
    def restore_origin(cls, data: dict[str, Any]) -> FiveDEngine:
        engine = FiveDEngine(
            max_timelines=int(data.get("max_timelines", 32)),
            max_turns=int(data.get("max_turns", 500)),
        )
        engine.timeline_manager = TimelineManager.from_dict(data["timeline_manager"])
        engine.timeline_manager.max_timelines = engine.max_timelines
        engine.game_state = GameState[data.get("game_state", "PLAYING")]
        engine.current_turn_color = ChessColor(data.get("current_turn_color", "white"))
        engine.move_history = []
        engine.action_history = []
        engine.move_counter = 0
        engine.current_action = ActionRules.begin(
            engine.current_turn_color,
            engine.timeline_manager.timelines,
        )
        engine._replay_origin = data
        return engine

    @classmethod
    def capture(cls, engine: FiveDEngine) -> dict[str, Any]:
        origin = getattr(engine, "_replay_origin", None)
        if origin is None:
            if engine.move_counter == 0:
                origin = cls.capture_origin(engine)
            else:
                origin = cls.default_origin(engine.max_timelines, engine.max_turns)
        return {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "replay_origin": origin,
            "max_timelines": engine.max_timelines,
            "max_turns": engine.max_turns,
            "timeline_manager": engine.timeline_manager.to_dict(),
            "game_state": engine.game_state.name,
            "move_counter": engine.move_counter,
            "current_turn_color": engine.current_turn_color.value,
            "move_history": [move_to_dict(move) for move in engine.move_history],
            "action_history": [action_to_dict(action) for action in engine.action_history],
            "current_action": action_to_dict(engine.current_action) if engine.current_action else None,
        }

    @classmethod
    def restore(cls, data: dict[str, Any]) -> FiveDEngine:
        version = int(data.get("schema_version", 1))
        if version < ARCHIVE_SCHEMA_VERSION:
            return cls.restore_legacy(data)
        if version != ARCHIVE_SCHEMA_VERSION:
            raise ValueError(f"unsupported archive schema_version={version}")

        engine = FiveDEngine(
            max_timelines=int(data.get("max_timelines", 32)),
            max_turns=int(data.get("max_turns", 500)),
        )
        engine.timeline_manager = TimelineManager.from_dict(data["timeline_manager"])
        engine.timeline_manager.max_timelines = engine.max_timelines
        engine.game_state = GameState[data.get("game_state", "PLAYING")]
        engine.current_turn_color = ChessColor(data.get("current_turn_color", "white"))
        engine.move_history = [move_from_dict(item) for item in data.get("move_history", [])]
        engine.move_counter = int(data.get("move_counter", len(engine.move_history)))
        engine.action_history = [action_from_dict(item) for item in data.get("action_history", [])]
        current = data.get("current_action")
        engine.current_action = (
            action_from_dict(current)
            if current
            else ActionRules.begin(engine.current_turn_color, engine.timeline_manager.timelines)
        )
        engine._replay_origin = data.get("replay_origin") or cls.default_origin(
            engine.max_timelines,
            engine.max_turns,
        )
        cls.validate(engine)
        return engine

    @classmethod
    def restore_legacy(cls, data: dict[str, Any]) -> FiveDEngine:
        engine = FiveDEngine(
            max_timelines=int(data.get("max_timelines", 32)),
            max_turns=int(data.get("max_turns", 500)),
        )
        engine.timeline_manager = TimelineManager.from_dict(data["timeline_manager"])
        engine.timeline_manager.max_timelines = engine.max_timelines
        engine.game_state = GameState[data.get("game_state", "PLAYING")]
        engine.current_turn_color = ChessColor(data.get("current_turn_color", "white"))
        moves = [legacy_move_from_dict(item) for item in data.get("move_history", [])]
        engine.move_history = moves
        engine.move_counter = int(data.get("move_counter", len(moves)))

        origin = cls.default_origin(engine.max_timelines, engine.max_turns)
        inferred = cls.restore_origin(origin)
        for move in moves:
            if not inferred.execute_action_move(move):
                break
            if inferred.can_submit_action():
                inferred.submit_action()
        engine.action_history = list(inferred.action_history)
        engine.current_action = ActionRules.begin(
            engine.current_turn_color,
            engine.timeline_manager.timelines,
        )
        engine._replay_origin = origin
        return engine

    @staticmethod
    def validate(engine: FiveDEngine) -> None:
        if engine.move_counter != len(engine.move_history):
            raise ValueError(
                "archive move_counter does not match move_history length: "
                f"{engine.move_counter} != {len(engine.move_history)}"
            )
        for action in engine.action_history:
            if not action.submitted:
                raise ValueError("action_history contains an unsubmitted Action")
        if engine.current_action is not None:
            if engine.current_action.submitted:
                raise ValueError("current_action cannot already be submitted")
            if engine.current_action.color != engine.current_turn_color:
                raise ValueError("current_action color disagrees with current_turn_color")

        flattened = [move for action in engine.action_history for move in action.moves]
        if engine.current_action is not None:
            flattened.extend(engine.current_action.moves)
        if flattened and flattened != engine.move_history:
            raise ValueError("Action move sequence disagrees with move_history")
