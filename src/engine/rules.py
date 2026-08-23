"""
5D Chess - 将军/将杀/和棋判定
"""
from __future__ import annotations
from src.utils.constants import ChessColor, PieceType
from src.engine.board import Position
from src.engine.move_generator import MoveGenerator
from src.engine.move_validator import MoveValidator


class RulesEngine:
    """规则判定引擎"""

    def __init__(self, timelines: dict[int, "Timeline"] = None):
        self.timelines = timelines or {}
        self.validator = MoveValidator(timelines)

    def is_check(self, position: Position) -> bool:
        """当前局面是否将军"""
        return self.validator.is_king_in_check(position, position.turn)

    def is_checkmate(self, position: Position) -> bool:
        """当前局面是否将杀（将军且无合法走子）"""
        if not self.is_check(position):
            return False
        generator = MoveGenerator(position, self.timelines)
        moves = generator.generate_all()
        legal = self.validator.filter_legal_moves(position, moves)
        return len(legal) == 0

    def is_stalemate(self, position: Position) -> bool:
        """当前局面是否逼和（无将军但无合法走子）"""
        if self.is_check(position):
            return False
        generator = MoveGenerator(position, self.timelines)
        moves = generator.generate_all()
        legal = self.validator.filter_legal_moves(position, moves)
        return len(legal) == 0

    def is_draw_by_insufficient_material(self, position: Position) -> bool:
        """无子可杀判和"""
        white_pieces = position.get_all_pieces(ChessColor.WHITE)
        black_pieces = position.get_all_pieces(ChessColor.BLACK)

        def count(pieces_list):
            result = {pt: 0 for pt in PieceType}
            for _, _, p in pieces_list:
                result[p.piece_type] += 1
            return result

        wc = count(white_pieces)
        bc = count(black_pieces)

        # 只有两王 → 和
        if len(white_pieces) == 1 and len(black_pieces) == 1:
            return True

        # 王+单象/单马 vs 王 → 和
        if len(white_pieces) == 2 and len(black_pieces) == 1:
            if wc[PieceType.BISHOP] == 1 or wc[PieceType.KNIGHT] == 1:
                return True
        if len(black_pieces) == 2 and len(white_pieces) == 1:
            if bc[PieceType.BISHOP] == 1 or bc[PieceType.KNIGHT] == 1:
                return True

        return False

    def get_game_result(self, position: Position) -> str | None:
        """获取游戏结果，无结果返回None"""
        if self.is_checkmate(position):
            winner = "black" if position.turn == ChessColor.WHITE else "white"
            return f"{winner}_win"
        if self.is_stalemate(position):
            return "draw"
        if self.is_draw_by_insufficient_material(position):
            return "draw"
        return None

    def check_all_timelines(self, active_boards: list[Position]) -> dict:
        """
        五维胜负判定：检查所有时间线的所有时间点
        返回 {"result": "white_win"|"black_win"|"draw"|None, "detail": str}
        """
        for pos in active_boards:
            result = self.get_game_result(pos)
            if result and result != "draw":
                return {"result": result, "detail": f"Timeline {pos.timeline_id}, t={pos.time_point}"}

        # 检查是否有任何一方在所有时间线中都无法移动
        # （简化处理：仅检查当前活跃棋盘）
        return {"result": None, "detail": ""}