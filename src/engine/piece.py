"""
5D Chess - 棋子定义
"""
from __future__ import annotations
from dataclasses import dataclass
from src.utils.constants import ChessColor, PieceType, PIECE_SYMBOLS


@dataclass(frozen=True, slots=True)
class Piece:
    """不可变棋子对象"""
    piece_type: PieceType
    color: ChessColor

    @property
    def symbol(self) -> str:
        return PIECE_SYMBOLS.get((self.color, self.piece_type), "?")

    @property
    def char(self) -> str:
        """返回字母表示，大写=白方，小写=黑方"""
        ch = self.piece_type.value
        return ch if self.color == ChessColor.WHITE else ch.lower()

    @property
    def value(self) -> int:
        from src.utils.constants import PIECE_VALUES
        return PIECE_VALUES[self.piece_type]

    def __repr__(self) -> str:
        return f"Piece({self.color.value} {self.piece_type.name})"


# 预定义棋子实例（可复用）
WHITE_KING = Piece(PieceType.KING, ChessColor.WHITE)
WHITE_QUEEN = Piece(PieceType.QUEEN, ChessColor.WHITE)
WHITE_ROOK = Piece(PieceType.ROOK, ChessColor.WHITE)
WHITE_BISHOP = Piece(PieceType.BISHOP, ChessColor.WHITE)
WHITE_KNIGHT = Piece(PieceType.KNIGHT, ChessColor.WHITE)
WHITE_PAWN = Piece(PieceType.PAWN, ChessColor.WHITE)

BLACK_KING = Piece(PieceType.KING, ChessColor.BLACK)
BLACK_QUEEN = Piece(PieceType.QUEEN, ChessColor.BLACK)
BLACK_ROOK = Piece(PieceType.ROOK, ChessColor.BLACK)
BLACK_BISHOP = Piece(PieceType.BISHOP, ChessColor.BLACK)
BLACK_KNIGHT = Piece(PieceType.KNIGHT, ChessColor.BLACK)
BLACK_PAWN = Piece(PieceType.PAWN, ChessColor.BLACK)

# Board cells are immutable one-character piece codes. Returning the canonical
# immutable Piece instances avoids allocating a fresh dataclass object for every
# board lookup in move generation, validation and royal-safety scans.
_PIECE_BY_CHAR: dict[str, Piece] = {
    "K": WHITE_KING,
    "Q": WHITE_QUEEN,
    "R": WHITE_ROOK,
    "B": WHITE_BISHOP,
    "N": WHITE_KNIGHT,
    "P": WHITE_PAWN,
    "k": BLACK_KING,
    "q": BLACK_QUEEN,
    "r": BLACK_ROOK,
    "b": BLACK_BISHOP,
    "n": BLACK_KNIGHT,
    "p": BLACK_PAWN,
}


def piece_from_char(ch: str) -> Piece | None:
    """从字符解析棋子，复用不可变的预定义实例。"""
    return _PIECE_BY_CHAR.get(ch)
