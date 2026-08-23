"""
5D Chess - 数据模型（ORM映射）
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
from src.utils.constants import ChessColor, PieceType, GameMode, AIDifficulty


@dataclass
class GameRecord:
    """游戏记录"""
    game_id: int | None = None
    mode: str = "pvp"
    player_white: str = "Player1"
    player_black: str = "Player2"
    ai_difficulty: str | None = None
    result: str = "ongoing"
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    total_moves: int = 0
    total_timelines: int = 1

    def to_dict(self) -> dict:
        data = asdict(self)
        data["start_time"] = self.start_time.isoformat() if self.start_time else None
        data["end_time"] = self.end_time.isoformat() if self.end_time else None
        return data


@dataclass
class TimelineRecord:
    """时间线记录"""
    timeline_id: int | None = None
    game_id: int = 0
    parent_id: int | None = None
    branch_move_id: int | None = None
    branch_turn: int | None = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class MoveRecord:
    """走子记录"""
    move_id: int | None = None
    game_id: int = 0
    timeline_id: int = 0
    turn_number: int = 0
    piece_type: str = ""
    piece_color: str = ""
    from_timeline_id: int = 0
    from_x: int = 0
    from_y: int = 0
    from_time: int = 0
    to_timeline_id: int = 0
    to_x: int = 0
    to_y: int = 0
    to_time: int = 0
    is_branching: bool = False
    new_timeline_id: int | None = None
    notation: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_move(cls, move, game_id: int, turn_number: int) -> "MoveRecord":
        """从引擎Move对象创建"""
        return cls(
            game_id=game_id,
            timeline_id=move.from_timeline_id,
            turn_number=turn_number,
            piece_type=move.piece.piece_type.value,
            piece_color=move.piece.color.value,
            from_timeline_id=move.from_timeline_id,
            from_x=move.from_x,
            from_y=move.from_y,
            from_time=move.from_time,
            to_timeline_id=move.to_timeline_id,
            to_x=move.to_x,
            to_y=move.to_y,
            to_time=move.to_time,
            is_branching=move.is_branching,
            new_timeline_id=getattr(move, "new_timeline_id", None),
            notation=move.to_notation(),
        )


@dataclass
class PositionRecord:
    """棋盘快照记录"""
    position_id: int | None = None
    timeline_id: int = 0
    turn_number: int = 0
    time_point: int = 0
    board_fen: str = ""
    board_json: str = ""
    active_color: str = "white"
    is_check: bool = False
    is_checkmate: bool = False


@dataclass
class GameStats:
    """对局统计"""
    stat_id: int | None = None
    game_id: int = 0
    avg_branch_depth: float = 0.0
    max_timelines: int = 0
    white_time_travels: int = 0
    black_time_travels: int = 0