"""
5D Chess - 走子生成器
生成所有伪合法走子（不考虑将军约束）
"""
from __future__ import annotations
from dataclasses import dataclass
from src.utils.constants import ChessColor, PieceType, BOARD_SIZE
from src.engine.piece import Piece
from src.engine.board import Position
from src.engine.coordinates import BoardCoord, Square5D, Vector4D
from src.engine.piece_movement import PieceMovementRules


@dataclass(frozen=True, slots=True)
class Move:
    """不可变走子对象。

    ``source`` / ``destination`` are the canonical coordinates. The legacy
    ``from_*`` / ``to_*`` attributes are exposed as read-only compatibility
    properties so the rest of the engine can migrate incrementally.
    """

    piece: Piece
    source: Square5D
    destination: Square5D
    captured: Piece | None = None
    promotion: PieceType | None = None
    is_castling: bool = False
    is_en_passant: bool = False
    is_branching: bool = False
    created_timeline: int | None = None

    @property
    def vector(self) -> Vector4D:
        """Return the canonical four-dimensional movement vector."""
        return self.source.vector_to(self.destination)

    @property
    def is_spatial(self) -> bool:
        """纯空间移动（同一棋盘内）"""
        return self.source.board == self.destination.board

    @property
    def is_time_travel(self) -> bool:
        """同时间线、不同时刻的移动"""
        return (
            self.source.timeline == self.destination.timeline
            and self.source.turn != self.destination.turn
        )

    @property
    def is_cross_timeline(self) -> bool:
        """跨时间线移动"""
        return self.source.timeline != self.destination.timeline

    # ---- Legacy compatibility accessors ---------------------------------
    # Engine/Replay/storage still index Position objects by half-move
    # ``time_point``. Canonical BoardCoord uses full turns, so convert only at
    # this boundary instead of contaminating 4D movement geometry.
    @property
    def from_x(self) -> int:
        return self.source.x

    @property
    def from_y(self) -> int:
        return self.source.y

    @property
    def to_x(self) -> int:
        return self.destination.x

    @property
    def to_y(self) -> int:
        return self.destination.y

    @property
    def from_timeline_id(self) -> int:
        return self.source.timeline

    @property
    def to_timeline_id(self) -> int:
        return self.destination.timeline

    @property
    def from_time(self) -> int:
        return self.source.board.legacy_time_point

    @property
    def to_time(self) -> int:
        return self.destination.board.legacy_time_point

    def to_notation(self) -> str:
        """生成棋谱记法（暂时保持现有格式兼容）"""
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

    KNIGHT_MOVES = [
        (-2, -1), (-2, 1), (-1, -2), (-1, 2),
        (1, -2), (1, 2), (2, -1), (2, 1),
    ]

    KING_MOVES = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    ]

    STRAIGHT_DIRS = [(0, 1), (0, -1), (1, 0), (-1, 0)]
    DIAGONAL_DIRS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]

    def __init__(self, position: Position, timelines: dict[int, "Timeline"] = None):
        self.position = position
        self.timelines = timelines or {}

    def _board_coord(
        self,
        *,
        timeline_id: int | None = None,
        legacy_time_point: int | None = None,
        side: ChessColor | None = None,
    ) -> BoardCoord:
        """Adapt a legacy Position half-move index into canonical board time."""
        time_point = (
            self.position.time_point
            if legacy_time_point is None
            else legacy_time_point
        )
        board_side = self.position.turn if side is None else side
        return BoardCoord.from_legacy_time_point(
            timeline=self.position.timeline_id if timeline_id is None else timeline_id,
            time_point=time_point,
            side=board_side,
        )

    def _square(
        self,
        x: int,
        y: int,
        *,
        timeline_id: int | None = None,
        legacy_time_point: int | None = None,
        side: ChessColor | None = None,
    ) -> Square5D:
        return Square5D(
            board=self._board_coord(
                timeline_id=timeline_id,
                legacy_time_point=legacy_time_point,
                side=side,
            ),
            x=x,
            y=y,
        )

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

        # 仍沿用当前项目的简化时间走法；目标棋盘至少先使用正确的
        # canonical turn/side 映射。下一阶段再按 Vector4D 枚举真实目标。
        moves.extend(self._gen_time_moves(color))
        return moves

    def _in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE

    def _make_move(self, piece: Piece, fx: int, fy: int, tx: int, ty: int,
                   captured: Piece | None = None, promotion: PieceType | None = None,
                   is_castling: bool = False, is_en_passant: bool = False) -> Move:
        board = self._board_coord()
        move = Move(
            piece=piece,
            source=Square5D(board, fx, fy),
            destination=Square5D(board, tx, ty),
            captured=captured,
            promotion=promotion,
            is_castling=is_castling,
            is_en_passant=is_en_passant,
        )

        if (
            piece.piece_type != PieceType.PAWN
            and not is_castling
            and not PieceMovementRules.is_valid(piece.piece_type, move.vector)
        ):
            raise ValueError(
                f"generated move violates {piece.piece_type.name} geometry: {move.vector}"
            )

        return move

    def _gen_pawn_moves(self, x: int, y: int, piece: Piece) -> list[Move]:
        moves = []
        direction = -1 if piece.color == ChessColor.WHITE else 1
        start_row = 6 if piece.color == ChessColor.WHITE else 1
        promotion_row = 0 if piece.color == ChessColor.WHITE else 7
        enemy_color = piece.color.opposite()

        ny = y + direction
        if self._in_bounds(x, ny) and self.position.is_empty(x, ny):
            if ny == promotion_row:
                for pt in [PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT]:
                    moves.append(self._make_move(piece, x, y, x, ny, promotion=pt))
            else:
                moves.append(self._make_move(piece, x, y, x, ny))

            if y == start_row:
                nny = y + 2 * direction
                if self._in_bounds(x, nny) and self.position.is_empty(x, nny):
                    moves.append(self._make_move(piece, x, y, x, nny))

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

            ep = self.position.en_passant_target
            if ep and ep == (nx, ny):
                moves.append(self._make_move(
                    piece, x, y, nx, ny,
                    captured=Piece(PieceType.PAWN, enemy_color),
                    is_en_passant=True
                ))

        return moves

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

    def _gen_bishop_moves(self, x: int, y: int, piece: Piece) -> list[Move]:
        return self._gen_sliding_moves(x, y, piece, self.DIAGONAL_DIRS)

    def _gen_rook_moves(self, x: int, y: int, piece: Piece) -> list[Move]:
        return self._gen_sliding_moves(x, y, piece, self.STRAIGHT_DIRS)

    def _gen_queen_moves(self, x: int, y: int, piece: Piece) -> list[Move]:
        return self._gen_sliding_moves(x, y, piece, self.STRAIGHT_DIRS + self.DIAGONAL_DIRS)

    def _gen_king_moves(self, x: int, y: int, piece: Piece) -> list[Move]:
        moves = []
        for dx, dy in self.KING_MOVES:
            nx, ny = x + dx, y + dy
            if not self._in_bounds(nx, ny):
                continue
            target = self.position.get_piece(nx, ny)
            if target is None or target.color != piece.color:
                moves.append(self._make_move(piece, x, y, nx, ny, captured=target))

        moves.extend(self._gen_castling_moves(x, y, piece))
        return moves

    def _gen_castling_moves(self, kx: int, ky: int, king: Piece) -> list[Move]:
        moves = []
        color = king.color
        rights = self.position.castling_rights
        row = 7 if color == ChessColor.WHITE else 0

        if kx != 4 or ky != row:
            return moves

        if rights.get(f"{color.value}_kingside", False):
            if self.position.is_empty(5, row) and self.position.is_empty(6, row):
                rook = self.position.get_piece(7, row)
                if rook and rook.piece_type == PieceType.ROOK and rook.color == color:
                    moves.append(self._make_move(king, kx, ky, 6, row, is_castling=True))

        if rights.get(f"{color.value}_queenside", False):
            if (self.position.is_empty(3, row) and self.position.is_empty(2, row)
                    and self.position.is_empty(1, row)):
                rook = self.position.get_piece(0, row)
                if rook and rook.piece_type == PieceType.ROOK and rook.color == color:
                    moves.append(self._make_move(king, kx, ky, 2, row, is_castling=True))

        return moves

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

    def _gen_time_moves(self, color: ChessColor) -> list[Move]:
        """生成当前项目已有的简化时间旅行移动。

        旧引擎的 ``time_point`` 是半步索引。这里只允许目标 half-move
        与当前棋子颜色相同，并把它转换为 canonical ``BoardCoord``，从而
        保证后续 ``Vector4D.dt`` 使用完整回合距离而不是被放大两倍。
        """
        moves = []
        tid = self.position.timeline_id
        current_time = self.position.time_point
        source_board = self._board_coord()
        source_timeline = self.timelines.get(tid)

        for target_time in range(current_time):
            if BoardCoord.legacy_side_for_time_point(target_time) != color:
                continue

            if source_timeline is not None:
                target_pos = source_timeline.positions.get(target_time)
                if target_pos is None or target_pos.turn != color:
                    continue

            target_board = self._board_coord(
                timeline_id=tid,
                legacy_time_point=target_time,
                side=color,
            )
            for x, y, piece in self.position.get_all_pieces(color):
                if piece.piece_type == PieceType.KING:
                    continue
                moves.append(Move(
                    piece=piece,
                    source=Square5D(source_board, x, y),
                    destination=Square5D(target_board, x, y),
                    is_branching=True,
                ))

        for other_tid, timeline in self.timelines.items():
            if other_tid == tid:
                continue
            if not timeline.is_active:
                continue
            if current_time not in timeline.positions:
                continue
            target_pos = timeline.positions[current_time]
            if target_pos.turn != color:
                continue
            target_board = BoardCoord.from_legacy_time_point(
                timeline=other_tid,
                time_point=current_time,
                side=target_pos.turn,
            )
            for x, y, piece in self.position.get_all_pieces(color):
                if target_pos.is_empty(x, y):
                    moves.append(Move(
                        piece=piece,
                        source=Square5D(source_board, x, y),
                        destination=Square5D(target_board, x, y),
                    ))

        return moves
