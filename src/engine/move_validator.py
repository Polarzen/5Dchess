"""
5D Chess - 走子合法性校验
过滤伪合法走子，确保走后己方王不被将军
"""
from __future__ import annotations
from src.utils.constants import ChessColor, PieceType, BOARD_SIZE
from src.engine.piece import Piece
from src.engine.board import Position
from src.engine.move_generator import Move, MoveGenerator


class MoveValidator:
    """走子合法性校验器"""

    def __init__(self, timelines: dict[int, "Timeline"] = None):
        self.timelines = timelines or {}

    def filter_legal_moves(self, position: Position, moves: list[Move]) -> list[Move]:
        """过滤出合法走子（走后己方王不被将军）"""
        legal = []
        for move in moves:
            if self._is_legal_after_move(position, move):
                legal.append(move)
        return legal

    def _is_legal_after_move(self, position: Position, move: Move) -> bool:
        """模拟走子后检查己方王是否被将军"""
        # 模拟走子
        new_pos = self._simulate_move(position, move)
        if new_pos is None:
            return False

        # 检查己方王是否被将军
        color = position.turn
        king_pos = new_pos.find_king(color)
        if king_pos is None:
            return False  # 王不存在（不应发生）

        return not self._is_square_attacked(new_pos, king_pos[0], king_pos[1], color.opposite())

    def _simulate_move(self, position: Position, move: Move) -> Position | None:
        """模拟走子，返回新棋盘"""
        if move.is_cross_timeline or move.is_branching:
            return self._simulate_special_move(position, move)

        new_pos = position.copy()
        new_pos.move_piece(move.from_x, move.from_y, move.to_x, move.to_y)

        # 处理王车易位
        if move.is_castling:
            row = move.to_y
            if move.to_x == 6:  # 短易位
                new_pos.move_piece(7, row, 5, row)
            elif move.to_x == 2:  # 长易位
                new_pos.move_piece(0, row, 3, row)

        # 处理过路兵
        if move.is_en_passant:
            direction = -1 if position.turn == ChessColor.WHITE else 1
            new_pos.set_piece(move.to_x, move.to_y - direction, None)

        # 处理升变
        if move.promotion:
            new_pos.set_piece(move.to_x, move.to_y, Piece(move.promotion, position.turn))

        new_pos.turn = position.turn.opposite()
        return new_pos

    def _simulate_special_move(self, position: Position, move: Move) -> Position | None:
        """模拟时间/跨时间线走子 — 简化处理，仅检查来源棋盘"""
        new_pos = position.copy()
        new_pos.move_piece(move.from_x, move.from_y, move.to_x, move.to_y)
        new_pos.turn = position.turn.opposite()
        return new_pos

    def _is_square_attacked(self, position: Position, x: int, y: int,
                            by_color: ChessColor) -> bool:
        """检查某格是否被指定颜色棋子攻击"""
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
        """检查某方王是否被将军"""
        king_pos = position.find_king(color)
        if king_pos is None:
            return False
        return self._is_square_attacked(position, king_pos[0], king_pos[1], color.opposite())