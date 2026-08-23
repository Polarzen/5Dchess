"""
5D Chess - 工具常量
"""
from enum import Enum, auto


class ChessColor(Enum):
    WHITE = "white"
    BLACK = "black"

    def opposite(self) -> "ChessColor":
        return ChessColor.BLACK if self == ChessColor.WHITE else ChessColor.WHITE


class PieceType(Enum):
    KING = "K"
    QUEEN = "Q"
    ROOK = "R"
    BISHOP = "B"
    KNIGHT = "N"
    PAWN = "P"

    @property
    def symbol(self) -> str:
        return self.value


class GameState(Enum):
    WAITING = auto()       # 等待开始
    PLAYING = auto()       # 对弈中
    CHECK = auto()         # 将军
    CHECKMATE = auto()     # 将杀
    STALEMATE = auto()     # 逼和
    DRAW = auto()          # 和棋
    RESIGNED = auto()      # 认输
    FINISHED = auto()      # 已结束


class GameMode(Enum):
    PVP = "pvp"
    PVE = "pve"
    REPLAY = "replay"


class AIDifficulty(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


# 棋子价值
PIECE_VALUES = {
    PieceType.KING: 10000,
    PieceType.QUEEN: 9,
    PieceType.ROOK: 5,
    PieceType.BISHOP: 3,
    PieceType.KNIGHT: 3,
    PieceType.PAWN: 1,
}

# 棋子Unicode符号
PIECE_SYMBOLS = {
    (ChessColor.WHITE, PieceType.KING): "♔",
    (ChessColor.WHITE, PieceType.QUEEN): "♕",
    (ChessColor.WHITE, PieceType.ROOK): "♖",
    (ChessColor.WHITE, PieceType.BISHOP): "♗",
    (ChessColor.WHITE, PieceType.KNIGHT): "♘",
    (ChessColor.WHITE, PieceType.PAWN): "♙",
    (ChessColor.BLACK, PieceType.KING): "♚",
    (ChessColor.BLACK, PieceType.QUEEN): "♛",
    (ChessColor.BLACK, PieceType.ROOK): "♜",
    (ChessColor.BLACK, PieceType.BISHOP): "♝",
    (ChessColor.BLACK, PieceType.KNIGHT): "♞",
    (ChessColor.BLACK, PieceType.PAWN): "♟",
}

# 初始棋盘 (FEN-like: 0=空, 白棋大写, 黑棋小写)
# K=King, Q=Queen, R=Rook, B=Bishop, N=Knight, P=Pawn
INITIAL_BOARD = [
    ["r", "n", "b", "q", "k", "b", "n", "r"],  # 黑方棋子 (row 0, top)
    ["p", "p", "p", "p", "p", "p", "p", "p"],  # 黑方兵
    ["", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", ""],
    ["P", "P", "P", "P", "P", "P", "P", "P"],  # 白方兵
    ["R", "N", "B", "Q", "K", "B", "N", "R"],  # 白方棋子 (row 7, bottom)
]

# 棋盘大小
BOARD_SIZE = 8

# 列名映射
COL_NAMES = "abcdefgh"
ROW_NAMES = "87654321"  # 棋盘从上到下