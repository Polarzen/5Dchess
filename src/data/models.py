"""Storage-facing data records for 5D Chess."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime

from src.data.archive import board_coord_to_dict


@dataclass
class GameRecord:
    game_id: int | None = None
    mode: str = "pvp"
    player_white: str = "Player1"
    player_black: str = "Player2"
    ai_difficulty: str | None = None
    result: str = "ongoing"
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    total_moves: int = 0
    total_actions: int = 0
    total_timelines: int = 1
    archive_version: int = 2

    def to_dict(self) -> dict:
        data = asdict(self)
        data["start_time"] = self.start_time.isoformat() if self.start_time else None
        data["end_time"] = self.end_time.isoformat() if self.end_time else None
        return data


@dataclass
class TimelineRecord:
    """One canonical signed-L lane inside a game."""

    timeline_row_id: int | None = None
    game_id: int = 0
    lane_id: int = 0
    parent_lane_id: int | None = None
    branch_move_id: int | None = None
    branch_turn: int | None = None
    owner: str | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ActionRecord:
    action_id: int | None = None
    game_id: int = 0
    action_index: int = 0
    color: str = "white"
    starting_present_json: str = "null"
    submitted: bool = False
    move_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_action(cls, action, game_id: int, action_index: int) -> "ActionRecord":
        present = action.starting_present
        payload = None
        if present is not None:
            payload = {
                "legacy_time_point": present.legacy_time_point,
                "turn": present.turn,
                "side": present.side.value,
                "boards": [board_coord_to_dict(board) for board in present.boards],
            }
        return cls(
            game_id=game_id,
            action_index=action_index,
            color=action.color.value,
            starting_present_json=json.dumps(payload, ensure_ascii=False),
            submitted=action.submitted,
            move_count=len(action.moves),
        )


@dataclass
class MoveRecord:
    """Canonical persisted Move; legacy half-move values are compatibility hints."""

    move_id: int | None = None
    game_id: int = 0
    action_index: int = 0
    move_index: int = 0
    piece_type: str = ""
    piece_color: str = ""

    source_timeline: int = 0
    source_turn: int = 0
    source_side: str = "white"
    source_x: int = 0
    source_y: int = 0

    destination_timeline: int = 0
    destination_turn: int = 0
    destination_side: str = "white"
    destination_x: int = 0
    destination_y: int = 0

    # Compatibility/debug representation only; canonical T+side above is primary.
    from_time: int = 0
    to_time: int = 0

    is_branching: bool = False
    is_cross_timeline: bool = False
    is_castling: bool = False
    is_en_passant: bool = False
    created_timeline: int | None = None
    captured_type: str | None = None
    captured_color: str | None = None
    promotion: str | None = None
    notation: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def timeline_id(self) -> int:
        return self.source_timeline

    @property
    def from_timeline_id(self) -> int:
        return self.source_timeline

    @property
    def to_timeline_id(self) -> int:
        return self.destination_timeline

    @property
    def from_x(self) -> int:
        return self.source_x

    @property
    def from_y(self) -> int:
        return self.source_y

    @property
    def to_x(self) -> int:
        return self.destination_x

    @property
    def to_y(self) -> int:
        return self.destination_y

    @property
    def new_timeline_id(self) -> int | None:
        return self.created_timeline

    @classmethod
    def from_move(
        cls,
        move,
        game_id: int,
        turn_number: int | None = None,
        *,
        action_index: int = 0,
        move_index: int = 0,
    ) -> "MoveRecord":
        captured = move.captured
        return cls(
            game_id=game_id,
            action_index=action_index if action_index is not None else (turn_number or 0),
            move_index=move_index,
            piece_type=move.piece.piece_type.value,
            piece_color=move.piece.color.value,
            source_timeline=move.source.board.timeline,
            source_turn=move.source.board.turn,
            source_side=move.source.board.side.value,
            source_x=move.source.x,
            source_y=move.source.y,
            destination_timeline=move.destination.board.timeline,
            destination_turn=move.destination.board.turn,
            destination_side=move.destination.board.side.value,
            destination_x=move.destination.x,
            destination_y=move.destination.y,
            from_time=move.source.board.legacy_time_point,
            to_time=move.destination.board.legacy_time_point,
            is_branching=move.is_branching,
            is_cross_timeline=move.is_cross_timeline,
            is_castling=move.is_castling,
            is_en_passant=move.is_en_passant,
            created_timeline=move.created_timeline,
            captured_type=captured.piece_type.value if captured else None,
            captured_color=captured.color.value if captured else None,
            promotion=move.promotion.value if move.promotion else None,
            notation=move.to_notation(),
        )


@dataclass
class PositionRecord:
    position_id: int | None = None
    game_id: int = 0
    lane_id: int = 0
    board_turn: int = 0
    board_side: str = "white"
    time_point: int = 0
    board_fen: str = ""
    board_json: str = ""
    is_playable: bool = False
    is_check: bool = False
    is_checkmate: bool = False

    @property
    def timeline_id(self) -> int:
        return self.lane_id

    @property
    def turn_number(self) -> int:
        return self.board_turn

    @property
    def active_color(self) -> str:
        return self.board_side


@dataclass
class GameStats:
    stat_id: int | None = None
    game_id: int = 0
    avg_branch_depth: float = 0.0
    max_timelines: int = 0
    white_time_travels: int = 0
    black_time_travels: int = 0
