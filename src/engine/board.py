"""
5D Chess - 棋盘表示
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, field
from src.utils.constants import (
    ChessColor, PieceType, INITIAL_BOARD, BOARD_SIZE, COL_NAMES, ROW_NAMES
)
from src.engine.piece import Piece, piece_from_char


@dataclass
class Position:
    """单个时间点的棋盘状态"""
    board: list[list[str]]           # 8×8 棋盘矩阵
    turn: ChessColor                 # 当前走子方
    timeline_id: int                 # 所属时间线
    time_point: int                  # 时间点(回合)
    move_number: int = 0             # 全局走子编号
    castling_rights: dict[str, bool] = field(default_factory=lambda: {
        "white_kingside": True,
        "white_queenside": True,
        "black_kingside": True,
        "black_queenside": True,
    })
    en_passant_target: tuple[int, int] | None = None  # 过路兵目标

    @classmethod
    def initial(cls, timeline_id: int = 0, time_point: int = 0) -> "Position":
        """创建初始棋盘状态"""
        board = [row[:] for row in INITIAL_BOARD]
        return cls(
            board=board,
            turn=ChessColor.WHITE,
            timeline_id=timeline_id,
            time_point=time_point,
        )

    def get_piece(self, x: int, y: int) -> Piece | None:
        """获取指定位置的棋子"""
        if not (0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE):
            return None
        return piece_from_char(self.board[y][x])

    def get_piece_char(self, x: int, y: int) -> str:
        """获取棋子字符"""
        if not (0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE):
            return ""
        return self.board[y][x]

    def set_piece(self, x: int, y: int, piece: Piece | None):
        """放置棋子"""
        self.board[y][x] = piece.char if piece else ""

    def move_piece(self, fx: int, fy: int, tx: int, ty: int) -> Piece | None:
        """移动棋子，返回被吃掉的棋子"""
        captured = self.get_piece(tx, ty)
        self.board[ty][tx] = self.board[fy][fx]
        self.board[fy][fx] = ""
        return captured

    def is_empty(self, x: int, y: int) -> bool:
        return self.get_piece(x, y) is None

    def is_occupied_by(self, x: int, y: int, color: ChessColor) -> bool:
        piece = self.get_piece(x, y)
        return piece is not None and piece.color == color

    def find_king(self, color: ChessColor) -> tuple[int, int] | None:
        """找到王的位置"""
        king_char = "K" if color == ChessColor.WHITE else "k"
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                if self.board[y][x] == king_char:
                    return (x, y)
        return None

    def get_all_pieces(self, color: ChessColor) -> list[tuple[int, int, Piece]]:
        """获取某方所有棋子"""
        result = []
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                piece = self.get_piece(x, y)
                if piece and piece.color == color:
                    result.append((x, y, piece))
        return result

    def copy(self) -> "Position":
        """深拷贝"""
        return deepcopy(self)

    def to_fen(self) -> str:
        """导出为标准FEN（不含时间信息）"""
        rows = []
        for y in range(BOARD_SIZE):
            empty = 0
            row_str = ""
            for x in range(BOARD_SIZE):
                ch = self.board[y][x]
                if ch:
                    if empty:
                        row_str += str(empty)
                        empty = 0
                    row_str += ch
                else:
                    empty += 1
            if empty:
                row_str += str(empty)
            rows.append(row_str)
        return "/".join(rows)

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "board": [row[:] for row in self.board],
            "turn": self.turn.value,
            "timeline_id": self.timeline_id,
            "time_point": self.time_point,
            "move_number": self.move_number,
            "castling_rights": self.castling_rights.copy(),
            "en_passant_target": self.en_passant_target,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        return cls(
            board=[row[:] for row in data["board"]],
            turn=ChessColor(data["turn"]),
            timeline_id=data["timeline_id"],
            time_point=data["time_point"],
            move_number=data.get("move_number", 0),
            castling_rights=data.get("castling_rights", {}).copy(),
            en_passant_target=data.get("en_passant_target"),
        )

    def __repr__(self) -> str:
        return f"Position(T{self.timeline_id}, t={self.time_point}, {self.turn.value})"