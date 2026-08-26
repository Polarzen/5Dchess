"""
5D Chess - 走子合法性校验

当前层仍保留项目原有的“单步、棋盘局部王安全”过滤语义；Action 级别的
完整 5D 将军/将杀规则会在后续单独实现。跨棋盘走子不再错误地模拟在一张
source Board 上，而是分别构造 source / destination 的结果棋盘。
"""
from __future__ import annotations

from dataclasses import dataclass

from src.utils.constants import ChessColor, PieceType, BOARD_SIZE
from src.engine.piece import Piece
from src.engine.board import Position
from src.engine.coordinates import BoardCoord
from src.engine.move_generator import Move, MoveGenerator
from src.engine.multiverse import MultiverseBoardView
from src.engine.path_rules import PathRules
from src.engine.pawn_rules import PawnRules
from src.engine.piece_movement import PieceMovementRules


@dataclass(frozen=True, slots=True)
class _MultiverseSimulation:
    """Board-local results of one cross-board move."""

    source_after: Position
    destination_after: Position


class MoveValidator:
    """走子合法性校验器。"""

    def __init__(self, timelines: dict[int, "Timeline"] = None):
        self.timelines = timelines or {}
        self.board_view = MultiverseBoardView(self.timelines)

    def filter_legal_moves(self, position: Position, moves: list[Move]) -> list[Move]:
        """过滤当前引擎可执行的 board-local 合法走子。"""
        return [move for move in moves if self._is_legal_after_move(position, move)]

    def _is_legal_after_move(self, position: Position, move: Move) -> bool:
        if not move.is_spatial:
            return self._is_legal_multiverse_move(position, move)

        if move.is_branching:
            return False

        new_pos = self._simulate_spatial_move(position, move)
        if new_pos is None:
            return False

        color = position.turn
        king_pos = new_pos.find_king(color)
        if king_pos is None:
            return False

        return not self._is_square_attacked(
            new_pos,
            king_pos[0],
            king_pos[1],
            color.opposite(),
        )

    def _simulate_spatial_move(self, position: Position, move: Move) -> Position | None:
        """模拟同一 Board 内走子，并严格验证 Pawn 特殊规则。"""
        actual_piece = position.get_piece(move.from_x, move.from_y)
        if actual_piece != move.piece or actual_piece.color != position.turn:
            return None

        target = position.get_piece(move.to_x, move.to_y)
        if target is not None and target.color == actual_piece.color:
            return None

        if actual_piece.piece_type == PieceType.PAWN:
            if not self._validate_spatial_pawn(position, move, target):
                return None

        new_pos = position.copy()
        new_pos.en_passant_target = None
        new_pos.move_piece(move.from_x, move.from_y, move.to_x, move.to_y)

        if move.is_castling:
            row = move.to_y
            if move.to_x == 6:
                new_pos.move_piece(7, row, 5, row)
            elif move.to_x == 2:
                new_pos.move_piece(0, row, 3, row)

        if move.is_en_passant:
            new_pos.set_piece(move.to_x, move.from_y, None)

        if move.promotion:
            new_pos.set_piece(
                move.to_x,
                move.to_y,
                Piece(move.promotion, position.turn),
            )

        if (
            actual_piece.piece_type == PieceType.PAWN
            and PawnRules.is_spatial_double(move.vector)
        ):
            new_pos.en_passant_target = (
                move.from_x,
                (move.from_y + move.to_y) // 2,
            )

        new_pos.turn = position.turn.opposite()
        return new_pos

    def _validate_spatial_pawn(
        self,
        position: Position,
        move: Move,
        target: Piece | None,
    ) -> bool:
        unmoved = position.is_pawn_unmoved(move.from_x, move.from_y)

        if move.is_en_passant:
            if target is not None or position.en_passant_target != (move.to_x, move.to_y):
                return False
            adjacent = position.get_piece(move.to_x, move.from_y)
            if (
                adjacent is None
                or adjacent.color == move.piece.color
                or adjacent.piece_type != PieceType.PAWN
                or adjacent != move.captured
            ):
                return False
            capture = True
        else:
            if target != move.captured:
                return False
            capture = target is not None

        if not PawnRules.is_valid_vector(
            move.piece.color,
            move.vector,
            capture=capture,
            unmoved=unmoved,
        ):
            return False

        if PawnRules.is_spatial_double(move.vector):
            middle_y = (move.from_y + move.to_y) // 2
            if position.get_piece(move.from_x, middle_y) is not None:
                return False

        promotes = PawnRules.reaches_promotion_rank(move.piece.color, move.to_y)
        if promotes:
            return PawnRules.is_valid_promotion(move.promotion)
        return move.promotion is None

    def _is_legal_multiverse_move(self, position: Position, move: Move) -> bool:
        """Validate geometry/state and local royal safety on both result boards."""
        simulation = self._simulate_multiverse_move(position, move)
        if simulation is None:
            return False

        color = move.piece.color
        return (
            self._local_king_safe(simulation.source_after, color)
            and self._local_king_safe(simulation.destination_after, color)
        )

    def _simulate_multiverse_move(
        self,
        position: Position,
        move: Move,
    ) -> _MultiverseSimulation | None:
        """Build source/destination board layouts for one non-spatial move."""
        if move.is_spatial or not self.timelines:
            return None

        source_coord = BoardCoord.from_legacy_time_point(
            timeline=position.timeline_id,
            time_point=position.time_point,
            side=position.turn,
        )
        if move.source.board != source_coord:
            return None
        if move.piece.color != position.turn:
            return None
        if move.destination.side != position.turn:
            return None

        source_description = self.board_view.describe(source_coord)
        if source_description is None or not source_description.is_playable:
            return None

        destination_description = self.board_view.describe(move.destination.board)
        if destination_description is None:
            return None

        if destination_description.is_historical != move.is_branching:
            return None

        actual_piece = position.get_piece(move.from_x, move.from_y)
        if actual_piece != move.piece:
            return None

        target_piece = destination_description.position.get_piece(move.to_x, move.to_y)
        if target_piece is not None and target_piece.color == move.piece.color:
            return None
        if target_piece != move.captured:
            return None

        if move.piece.piece_type == PieceType.PAWN:
            if not self._validate_multiverse_pawn(
                position,
                move,
                target_piece,
            ):
                return None
        else:
            try:
                if not PieceMovementRules.is_valid(move.piece.piece_type, move.vector):
                    return None
            except ValueError:
                return None

            if (
                PieceMovementRules.is_slider(move.piece.piece_type)
                and not PathRules.is_clear(
                    move.piece.piece_type,
                    move.source,
                    move.destination,
                    self.board_view.resolve,
                )
            ):
                return None

        source_after = position.copy()
        source_after.en_passant_target = None
        source_after.set_piece(move.from_x, move.from_y, None)

        destination_after = destination_description.position.copy()
        destination_after.en_passant_target = None
        destination_after.set_piece(move.to_x, move.to_y, move.piece)

        return _MultiverseSimulation(
            source_after=source_after,
            destination_after=destination_after,
        )

    def _validate_multiverse_pawn(
        self,
        position: Position,
        move: Move,
        target_piece: Piece | None,
    ) -> bool:
        # En passant and promotion are not generalized across boards.
        if move.is_en_passant or move.promotion is not None:
            return False

        capture = target_piece is not None
        if not PawnRules.is_valid_vector(
            move.piece.color,
            move.vector,
            capture=capture,
            unmoved=position.is_pawn_unmoved(move.from_x, move.from_y),
        ):
            return False

        if PawnRules.is_timeline_double(move.vector):
            intermediate_coord = BoardCoord(
                timeline=(
                    move.source.timeline
                    + PawnRules.timeline_forward(move.piece.color)
                ),
                turn=move.source.turn,
                side=move.source.side,
            )
            intermediate = self.board_view.resolve(intermediate_coord)
            if (
                intermediate is None
                or intermediate.get_piece(move.from_x, move.from_y) is not None
            ):
                return False

        return True

    def _local_king_safe(self, position: Position, color: ChessColor) -> bool:
        """Check standard 2D attacks if this board contains the color's king."""
        king_pos = position.find_king(color)
        if king_pos is None:
            return True
        return not self._is_square_attacked(
            position,
            king_pos[0],
            king_pos[1],
            color.opposite(),
        )

    def _is_square_attacked(self, position: Position, x: int, y: int,
                            by_color: ChessColor) -> bool:
        """检查单张棋盘上某格是否被指定颜色棋子攻击。"""
        return self._attacked_by_pawn(position, x, y, by_color) \
            or self._attacked_by_knight(position, x, y, by_color) \
            or self._attacked_by_bishop_queen(position, x, y, by_color) \
            or self._attacked_by_rook_queen(position, x, y, by_color) \
            or self._attacked_by_king(position, x, y, by_color)

    def _attacked_by_pawn(self, pos: Position, x: int, y: int, by: ChessColor) -> bool:
        direction = 1 if by == ChessColor.WHITE else -1
        for dx in [-1, 1]:
            nx, ny = x + dx, y + direction
            if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE:
                p = pos.get_piece(nx, ny)
                if p and p.color == by and p.piece_type == PieceType.PAWN:
                    return True
        return False

    def _attacked_by_knight(self, pos: Position, x: int, y: int, by: ChessColor) -> bool:
        for dx, dy in MoveGenerator.KNIGHT_MOVES:
            nx, ny = x + dx, y + dy
            if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE:
                p = pos.get_piece(nx, ny)
                if p and p.color == by and p.piece_type == PieceType.KNIGHT:
                    return True
        return False

    def _attacked_by_king(self, pos: Position, x: int, y: int, by: ChessColor) -> bool:
        for dx, dy in MoveGenerator.KING_MOVES:
            nx, ny = x + dx, y + dy
            if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE:
                p = pos.get_piece(nx, ny)
                if p and p.color == by and p.piece_type == PieceType.KING:
                    return True
        return False

    def _attacked_by_bishop_queen(self, pos: Position, x: int, y: int, by: ChessColor) -> bool:
        for dx, dy in MoveGenerator.DIAGONAL_DIRS:
            nx, ny = x + dx, y + dy
            while 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE:
                p = pos.get_piece(nx, ny)
                if p:
                    if p.color == by and p.piece_type in (PieceType.BISHOP, PieceType.QUEEN):
                        return True
                    break
                nx += dx
                ny += dy
        return False

    def _attacked_by_rook_queen(self, pos: Position, x: int, y: int, by: ChessColor) -> bool:
        for dx, dy in MoveGenerator.STRAIGHT_DIRS:
            nx, ny = x + dx, y + dy
            while 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE:
                p = pos.get_piece(nx, ny)
                if p:
                    if p.color == by and p.piece_type in (PieceType.ROOK, PieceType.QUEEN):
                        return True
                    break
                nx += dx
                ny += dy
        return False

    def is_king_in_check(self, position: Position, color: ChessColor) -> bool:
        """检查单张棋盘上的王是否被二维攻击。"""
        king_pos = position.find_king(color)
        if king_pos is None:
            return False
        return self._is_square_attacked(
            position,
            king_pos[0],
            king_pos[1],
            color.opposite(),
        )
