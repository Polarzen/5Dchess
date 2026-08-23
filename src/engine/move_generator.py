"""
5D Chess - 走子生成器
生成所有伪合法走子（不考虑将军约束）
"""
from __future__ import annotations
from dataclasses import dataclass
from src.utils.constants import ChessColor, PieceType, BOARD_SIZE
from src.engine.piece import Piece
from src.engine.board import Position


@dataclass(frozen=True, slots=True)
class Move:
    """不可变走子对象"""
    piece: Piece
    from_x: int
    from_y: int
    to_x: int
    to_y: int
    from_timeline_id: int
    to_timeline_id: int
    from_time: int
    to_time: int
    is_branching: bool = False
    captured: Piece | None = None
    promotion: PieceType | None = None
    is_castling: bool = False
    is_en_passant: bool = False

    @property
    def is_spatial(self) -> bool:
        """纯空间移动（同时间线，同时刻）"""
        return (self.from_timeline_id == self.to_timeline_id
                and self.from_time == self.to_time)

    @property
    def is_time_travel(self) -> bool:
        """时间移动（同时间线，不同时间）"""
        return (self.from_timeline_id == self.to_timeline_id
                and self.from_time != self.to_time)

    @property
    def is_cross_timeline(self) -> bool:
        """跨时间线移动"""
        return self.from_timeline_id != self.to_timeline_id

    def to_notation(self) -> str:
        """生成棋谱记法"""
        if self.is_cross_timeline:
            base = f"({self.from_timeline_id}→{self.to_timeline_id})"
        else:
            base = f"(T{self.from_timeline_id})"
        piece_sym = self.piece.piece_type.value if self.piece.piece_type != PieceType.PAWN else ""
        from_sq = f"{chr(97+self.from_x)}{self.from_y+1}"
        to_sq = f"{chr(97+self.to_x)}{self.to_y+1}"
        capture = "x" if self.captured else "-"
        time_info = f"t{self.to_time}" if self.to_time != self.from_time else ""
        return f"{base} {piece_sym}{from_sq}{capture}{to_sq}{time_info}".strip()

    def __repr__(self) -> str:
        return self.to_notation()


class MoveGenerator:
    """走子生成器 — 生成所有伪合法走子"""

    # 马步
    KNIGHT_MOVES = [
        (-2, -1), (-2, 1), (-1, -2), (-1, 2),
        (1, -2), (1, 2), (2, -1), (2, 1),
    ]

    # 王步（含对角线）
    KING_MOVES = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    ]

    # 直线方向
    STRAIGHT_DIRS = [(0, 1), (0, -1), (1, 0), (-1, 0)]
    # 对角线方向
    DIAGONAL_DIRS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]

    def __init__(self, position: Position, timelines: dict[int, "Timeline"] = None):
        self.position = position
        self.timelines = timelines or {}

    def generate_all(self) -> list[Move]:
        """生成所有伪合法走子"""
        moves: list[Move] = []
        color = self.position.turn

        for x, y, piece in self.position.get_all_pieces(color):
            if piece.piece_type == PieceType.PAWN:
                moves.extend(self._gen_pawn_moves(x, y, piece))
            elif piece.piece_type == PieceType.KNIGHT:
                moves.extend(self._gen_knight_moves(x, y, piece))
            elif piece.piece_type == PieceType.BISHOP:
                moves.extend(self._gen_bishop_moves(x, y, piece))
            elif piece.piece_type == PieceType.ROOK:
                moves.extend(self._gen_rook_moves(x, y, piece))
            elif piece.piece_type == PieceType.QUEEN:
                moves.extend(self._gen_queen_moves(x, y, piece))
            elif piece.piece_type == PieceType.KING:
                moves.extend(self._gen_king_moves(x, y, piece))

        # 添加时间移动（五维特有）
        moves.extend(self._gen_time_moves(color))

        return moves

    def _in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE

    def _make_move(self, piece: Piece, fx: int, fy: int, tx: int, ty: int,
                   captured: Piece | None = None, promotion: PieceType | None = None,
                   is_castling: bool = False, is_en_passant: bool = False) -> Move:
        return Move(
            piece=piece,
            from_x=fx, from_y=fy,
            to_x=tx, to_y=ty,
            from_timeline_id=self.position.timeline_id,
            to_timeline_id=self.position.timeline_id,
            from_time=self.position.time_point,
            to_time=self.position.time_point,
            captured=captured,
            promotion=promotion,
            is_castling=is_castling,
            is_en_passant=is_en_passant,
        )

    # ─── 兵 ────────────────────────────────────────────

    def _gen_pawn_moves(self, x: int, y: int, piece: Piece) -> list[Move]:
        moves = []
        direction = -1 if piece.color == ChessColor.WHITE else 1
        start_row = 6 if piece.color == ChessColor.WHITE else 1
        promotion_row = 0 if piece.color == ChessColor.WHITE else 7
        enemy_color = piece.color.opposite()

        # 前进一格
        ny = y + direction
        if self._in_bounds(x, ny) and self.position.is_empty(x, ny):
            if ny == promotion_row:
                for pt in [PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT]:
                    moves.append(self._make_move(piece, x, y, x, ny, promotion=pt))
            else:
                moves.append(self._make_move(piece, x, y, x, ny))

            # 前进两格（初始位置）
            if y == start_row:
                nny = y + 2 * direction
                if self._in_bounds(x, nny) and self.position.is_empty(x, nny):
                    moves.append(self._make_move(piece, x, y, x, nny))

        # 斜吃
        for dx in [-1, 1]:
            nx = x + dx
            if not self._in_bounds(nx, ny):
                continue
            target = self.position.get_piece(nx, ny)
            if target and target.color == enemy_color:
                if ny == promotion_row:
                    for pt in [PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT]:
                        moves.append(self._make_move(piece, x, y, nx, ny, captured=target, promotion=pt))
                else:
                    moves.append(self._make_move(piece, x, y, nx, ny, captured=target))

            # 过路兵
            ep = self.position.en_passant_target
            if ep and ep == (nx, ny):
                moves.append(self._make_move(
                    piece, x, y, nx, ny,
                    captured=Piece(PieceType.PAWN, enemy_color),
                    is_en_passant=True
                ))

        return moves

    # ─── 马 ────────────────────────────────────────────

    def _gen_knight_moves(self, x: int, y: int, piece: Piece) -> list[Move]:
        moves = []
        for dx, dy in self.KNIGHT_MOVES:
            nx, ny = x + dx, y + dy
            if not self._in_bounds(nx, ny):
                continue
            target = self.position.get_piece(nx, ny)
            if target is None or target.color != piece.color:
                moves.append(self._make_move(piece, x, y, nx, ny, captured=target))
        return moves

    # ─── 象 ────────────────────────────────────────────

    def _gen_bishop_moves(self, x: int, y: int, piece: Piece) -> list[Move]:
        return self._gen_sliding_moves(x, y, piece, self.DIAGONAL_DIRS)

    # ─── 车 ────────────────────────────────────────────

    def _gen_rook_moves(self, x: int, y: int, piece: Piece) -> list[Move]:
        return self._gen_sliding_moves(x, y, piece, self.STRAIGHT_DIRS)

    # ─── 后 ────────────────────────────────────────────

    def _gen_queen_moves(self, x: int, y: int, piece: Piece) -> list[Move]:
        return self._gen_sliding_moves(x, y, piece, self.STRAIGHT_DIRS + self.DIAGONAL_DIRS)

    # ─── 王 ────────────────────────────────────────────

    def _gen_king_moves(self, x: int, y: int, piece: Piece) -> list[Move]:
        moves = []
        for dx, dy in self.KING_MOVES:
            nx, ny = x + dx, y + dy
            if not self._in_bounds(nx, ny):
                continue
            target = self.position.get_piece(nx, ny)
            if target is None or target.color != piece.color:
                moves.append(self._make_move(piece, x, y, nx, ny, captured=target))

        # 王车易位
        moves.extend(self._gen_castling_moves(x, y, piece))
        return moves

    def _gen_castling_moves(self, kx: int, ky: int, king: Piece) -> list[Move]:
        """生成王车易位走子"""
        moves = []
        color = king.color
        rights = self.position.castling_rights
        row = 7 if color == ChessColor.WHITE else 0

        # 王必须在原位
        if kx != 4 or ky != row:
            return moves

        # 短易位 (Kingside)
        if rights.get(f"{color.value}_kingside", False):
            if (self.position.is_empty(5, row) and self.position.is_empty(6, row)):
                rook = self.position.get_piece(7, row)
                if rook and rook.piece_type == PieceType.ROOK and rook.color == color:
                    moves.append(self._make_move(king, kx, ky, 6, row, is_castling=True))

        # 长易位 (Queenside)
        if rights.get(f"{color.value}_queenside", False):
            if (self.position.is_empty(3, row) and self.position.is_empty(2, row)
                    and self.position.is_empty(1, row)):
                rook = self.position.get_piece(0, row)
                if rook and rook.piece_type == PieceType.ROOK and rook.color == color:
                    moves.append(self._make_move(king, kx, ky, 2, row, is_castling=True))

        return moves

    # ─── 滑动走子通用 ──────────────────────────────────

    def _gen_sliding_moves(self, x: int, y: int, piece: Piece,
                           directions: list[tuple[int, int]]) -> list[Move]:
        moves = []
        for dx, dy in directions:
            nx, ny = x + dx, y + dy
            while self._in_bounds(nx, ny):
                target = self.position.get_piece(nx, ny)
                if target is None:
                    moves.append(self._make_move(piece, x, y, nx, ny))
                elif target.color != piece.color:
                    moves.append(self._make_move(piece, x, y, nx, ny, captured=target))
                    break
                else:
                    break
                nx += dx
                ny += dy
        return moves

    # ─── 时间移动（五维特有）────────────────────────────

    def _gen_time_moves(self, color: ChessColor) -> list[Move]:
        """生成时间旅行移动"""
        moves = []
        tid = self.position.timeline_id
        current_time = self.position.time_point

        # 向过去移动 → 产生分支
        for target_time in range(current_time):
            for x, y, piece in self.position.get_all_pieces(color):
                if piece.piece_type == PieceType.KING:
                    continue  # 王不能时间旅行
                moves.append(Move(
                    piece=piece,
                    from_x=x, from_y=y,
                    to_x=x, to_y=y,
                    from_timeline_id=tid,
                    to_timeline_id=tid,
                    from_time=current_time,
                    to_time=target_time,
                    is_branching=True,
                ))

        # 跨时间线移动（同一时间点，不同时间线）
        for other_tid, timeline in self.timelines.items():
            if other_tid == tid:
                continue
            if not timeline.is_active:
                continue
            # 找到目标时间线中同时间点的棋盘
            if current_time not in timeline.positions:
                continue
            target_pos = timeline.positions[current_time]
            for x, y, piece in self.position.get_all_pieces(color):
                # 目标位置必须为空
                if target_pos.is_empty(x, y):
                    moves.append(Move(
                        piece=piece,
                        from_x=x, from_y=y,
                        to_x=x, to_y=y,
                        from_timeline_id=tid,
                        to_timeline_id=other_tid,
                        from_time=current_time,
                        to_time=current_time,
                    ))

        return moves