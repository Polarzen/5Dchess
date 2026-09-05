"""
5D Chess - 走子生成器
生成所有伪合法走子（不考虑将军约束）
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from src.utils.constants import ChessColor, PieceType, BOARD_SIZE
from src.engine.piece import Piece
from src.engine.board import Position
from src.engine.coordinates import BoardCoord, Square5D, Vector4D
from src.engine.multiverse import MultiverseBoardView
from src.engine.path_rules import PathRules
from src.engine.pawn_rules import PawnRules
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
    """走子生成器 — 生成所有伪合法走子。

    R/B/Q/K/N use symmetric 4D geometry. Pawns use a dedicated color-relative
    rule layer: forward is Y or L, captures are confined to the X/Y or T/L
    plane, and multiverse en-passant is intentionally not generalized.
    """

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
        self.board_view = MultiverseBoardView(self.timelines)

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
        """生成当前可玩棋盘上的所有伪合法走子。"""
        color = self.position.turn
        source_board = self._board_coord()

        if self.timelines:
            source = self.board_view.describe(source_board)
            if source is not None and not source.is_playable:
                return []

        moves: list[Move] = []
        for x, y, piece in self.position.get_all_pieces(color):
            moves.extend(self._gen_spatial_piece_moves(x, y, piece))

        moves.extend(self._gen_multiverse_moves(color))
        return moves

    def generate_from_square(self, x: int, y: int) -> list[Move]:
        """Generate pseudo-legal Moves for exactly one source square.

        This is semantically the same subset that ``generate_all`` would emit
        for the source piece. It exists so callers validating one immutable
        MoveSpec do not regenerate every other piece's moves first.
        """
        color = self.position.turn
        source_board = self._board_coord()

        if self.timelines:
            source = self.board_view.describe(source_board)
            if source is not None and not source.is_playable:
                return []

        piece = self.position.get_piece(x, y)
        if piece is None or piece.color != color:
            return []

        moves = self._gen_spatial_piece_moves(x, y, piece)
        if not self.timelines:
            return moves

        target_boards = tuple(self.board_view.iter_boards(side=color))
        if piece.piece_type == PieceType.PAWN:
            moves.extend(self._gen_pawn_multiverse_moves(
                x,
                y,
                piece,
                target_boards,
            ))
        elif PieceMovementRules.supports(piece.piece_type):
            moves.extend(self._gen_piece_multiverse_moves(
                x,
                y,
                piece,
                target_boards,
            ))
        return moves

    def _gen_spatial_piece_moves(self, x: int, y: int, piece: Piece) -> list[Move]:
        """Generate the same-board pseudo-legal subset for one piece."""
        if piece.piece_type == PieceType.PAWN:
            return self._gen_pawn_moves(x, y, piece)
        if piece.piece_type == PieceType.KNIGHT:
            return self._gen_knight_moves(x, y, piece)
        if piece.piece_type == PieceType.BISHOP:
            return self._gen_bishop_moves(x, y, piece)
        if piece.piece_type == PieceType.ROOK:
            return self._gen_rook_moves(x, y, piece)
        if piece.piece_type == PieceType.QUEEN:
            return self._gen_queen_moves(x, y, piece)
        if piece.piece_type == PieceType.KING:
            return self._gen_king_moves(x, y, piece)
        return []

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
        """Generate same-board pawn moves using standard 5D pawn semantics."""
        moves: list[Move] = []
        direction = PawnRules.spatial_forward(piece.color)
        promotion_row = PawnRules.promotion_rank(piece.color)
        enemy_color = piece.color.opposite()
        unmoved = self.position.is_pawn_unmoved(x, y)

        ny = y + direction
        if self._in_bounds(x, ny) and self.position.is_empty(x, ny):
            promotion = PieceType.QUEEN if ny == promotion_row else None
            moves.append(self._make_move(
                piece, x, y, x, ny, promotion=promotion
            ))

            if unmoved:
                nny = y + 2 * direction
                if self._in_bounds(x, nny) and self.position.is_empty(x, nny):
                    moves.append(self._make_move(piece, x, y, x, nny))

        for dx in (-1, 1):
            nx = x + dx
            if not self._in_bounds(nx, ny):
                continue

            target = self.position.get_piece(nx, ny)
            if target and target.color == enemy_color:
                promotion = PieceType.QUEEN if ny == promotion_row else None
                moves.append(self._make_move(
                    piece,
                    x,
                    y,
                    nx,
                    ny,
                    captured=target,
                    promotion=promotion,
                ))
                continue

            # En passant remains a same-board rule only. Require the actual
            # adjacent enemy pawn instead of synthesizing a capture blindly.
            ep = self.position.en_passant_target
            adjacent = self.position.get_piece(nx, y)
            if (
                target is None
                and ep == (nx, ny)
                and adjacent is not None
                and adjacent.color == enemy_color
                and adjacent.piece_type == PieceType.PAWN
            ):
                moves.append(self._make_move(
                    piece,
                    x,
                    y,
                    nx,
                    ny,
                    captured=adjacent,
                    is_en_passant=True,
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

    def _gen_multiverse_moves(self, color: ChessColor) -> list[Move]:
        """Generate cross-board moves for all pieces on the source board."""
        if not self.timelines:
            return []

        source_board = self._board_coord()
        source_description = self.board_view.describe(source_board)
        if source_description is None or not source_description.is_playable:
            return []

        target_boards = tuple(self.board_view.iter_boards(side=color))
        moves: list[Move] = []

        for x, y, piece in self.position.get_all_pieces(color):
            if piece.piece_type == PieceType.PAWN:
                moves.extend(self._gen_pawn_multiverse_moves(
                    x,
                    y,
                    piece,
                    target_boards,
                ))
            elif PieceMovementRules.supports(piece.piece_type):
                moves.extend(self._gen_piece_multiverse_moves(
                    x,
                    y,
                    piece,
                    target_boards,
                ))
        return moves

    def _gen_piece_multiverse_moves(
        self,
        x: int,
        y: int,
        piece: Piece,
        target_boards,
    ) -> list[Move]:
        """Generate non-pawn cross-board Moves for one source piece."""
        source = Square5D(self._board_coord(), x, y)
        moves: list[Move] = []

        for target_board in target_boards:
            if target_board.coord == source.board:
                continue

            dt = target_board.coord.turn - source.turn
            dl = target_board.coord.timeline - source.timeline
            for dx, dy in self._candidate_spatial_offsets(
                piece.piece_type, dt, dl
            ):
                tx, ty = x + dx, y + dy
                if not self._in_bounds(tx, ty):
                    continue

                destination = Square5D(target_board.coord, tx, ty)
                vector = source.vector_to(destination)
                if not PieceMovementRules.is_valid(piece.piece_type, vector):
                    continue

                if (
                    PieceMovementRules.is_slider(piece.piece_type)
                    and not PathRules.is_clear(
                        piece.piece_type,
                        source,
                        destination,
                        self.board_view.resolve,
                    )
                ):
                    continue

                captured = target_board.position.get_piece(tx, ty)
                if captured is not None and captured.color == piece.color:
                    continue

                moves.append(Move(
                    piece=piece,
                    source=source,
                    destination=destination,
                    captured=captured,
                    is_branching=target_board.is_historical,
                ))

        return moves

    def _gen_pawn_multiverse_moves(
        self,
        x: int,
        y: int,
        piece: Piece,
        target_boards,
    ) -> list[Move]:
        """Generate pawn advances/captures in the temporal T/L plane."""
        source = Square5D(self._board_coord(), x, y)
        unmoved = self.position.is_pawn_unmoved(x, y)
        moves: list[Move] = []

        for target_board in target_boards:
            if target_board.coord == source.board:
                continue

            # Standard temporal pawn movement never changes X/Y.
            destination = Square5D(target_board.coord, x, y)
            target = target_board.position.get_piece(x, y)
            if target is not None and target.color == piece.color:
                continue

            vector = source.vector_to(destination)
            capture = target is not None
            if not PawnRules.is_valid_vector(
                piece.color,
                vector,
                capture=capture,
                unmoved=unmoved,
            ):
                continue

            if PawnRules.is_timeline_double(vector):
                intermediate_coord = BoardCoord(
                    timeline=source.timeline + PawnRules.timeline_forward(piece.color),
                    turn=source.turn,
                    side=source.side,
                )
                intermediate = self.board_view.resolve(intermediate_coord)
                if intermediate is None or intermediate.get_piece(x, y) is not None:
                    continue

            moves.append(Move(
                piece=piece,
                source=source,
                destination=destination,
                captured=target,
                is_branching=target_board.is_historical,
            ))

        return moves

    @staticmethod
    def _candidate_spatial_offsets(
        piece_type: PieceType,
        dt: int,
        dl: int,
    ) -> tuple[tuple[int, int], ...]:
        """Infer the small set of (dx, dy) candidates from fixed T/L deltas."""
        board_components = tuple(value for value in (dt, dl) if value != 0)
        if not board_components:
            return ()

        if piece_type == PieceType.ROOK:
            return ((0, 0),) if len(board_components) == 1 else ()

        if piece_type == PieceType.BISHOP:
            if len(board_components) == 2:
                if abs(board_components[0]) != abs(board_components[1]):
                    return ()
                return ((0, 0),)

            magnitude = abs(board_components[0])
            return (
                (-magnitude, 0),
                (magnitude, 0),
                (0, -magnitude),
                (0, magnitude),
            )

        if piece_type == PieceType.QUEEN:
            magnitudes = {abs(value) for value in board_components}
            if len(magnitudes) != 1:
                return ()
            magnitude = magnitudes.pop()
            values = (-magnitude, 0, magnitude)
            return tuple(product(values, repeat=2))

        if piece_type == PieceType.KING:
            if any(abs(value) != 1 for value in board_components):
                return ()
            return tuple(product((-1, 0, 1), repeat=2))

        if piece_type == PieceType.KNIGHT:
            if len(board_components) == 2:
                return (
                    ((0, 0),)
                    if sorted(abs(value) for value in board_components) == [1, 2]
                    else ()
                )

            magnitude = abs(board_components[0])
            if magnitude not in (1, 2):
                return ()
            spatial_magnitude = 2 if magnitude == 1 else 1
            return (
                (-spatial_magnitude, 0),
                (spatial_magnitude, 0),
                (0, -spatial_magnitude),
                (0, spatial_magnitude),
            )

        return ()
