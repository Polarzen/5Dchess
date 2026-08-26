"""
5D Chess - 走子生成器测试
"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine import Position, MoveGenerator, MoveValidator
from src.utils.constants import ChessColor, PieceType


class TestPawnMoves:
    def test_white_pawn_forward_one(self):
        pos = Position.initial()
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        # e2-e3
        e2_e3 = [m for m in moves if m.from_x == 4 and m.from_y == 6 and m.to_x == 4 and m.to_y == 5]
        assert len(e2_e3) == 1

    def test_white_pawn_forward_two(self):
        pos = Position.initial()
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        e2_e4 = [m for m in moves if m.from_x == 4 and m.from_y == 6 and m.to_y == 4]
        assert len(e2_e4) == 1

    def test_pawn_capture(self):
        """测试兵斜吃"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[4][4] = "P"
        board[3][5] = "p"
        board[0][0] = "K"
        board[7][7] = "k"
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        captures = [m for m in moves if m.captured]
        assert len(captures) >= 1

    def test_promotion(self):
        """标准 5D Pawn 到底线后只能升变为 Queen。"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[0][4] = ""
        board[1][4] = "P"
        board[7][0] = "K"
        board[0][7] = "k"
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        promotions = [m for m in moves if m.promotion]
        assert len(promotions) == 1
        assert promotions[0].promotion == PieceType.QUEEN


class TestKnightMoves:
    def test_knight_center(self):
        """测试马在中心"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[4][4] = "N"
        board[0][0] = "K"
        board[7][7] = "k"
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        knight_moves = [m for m in moves if m.piece.piece_type == PieceType.KNIGHT]
        assert len(knight_moves) == 8


class TestSlidingMoves:
    def test_rook_open_file(self):
        """测试车在开放线"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[4][4] = "R"
        board[0][0] = "K"
        board[7][7] = "k"
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        rook_moves = [m for m in moves if m.piece.piece_type == PieceType.ROOK]
        assert len(rook_moves) == 14

    def test_bishop_diagonal(self):
        """测试象在斜线"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[4][4] = "B"
        board[0][0] = "K"
        board[7][7] = "k"
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        bishop_moves = [m for m in moves if m.piece.piece_type == PieceType.BISHOP]
        assert len(bishop_moves) == 12

    def test_queen_center(self):
        """测试后在中心"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[4][4] = "Q"
        board[0][0] = "K"
        board[7][7] = "k"
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        queen_moves = [m for m in moves if m.piece.piece_type == PieceType.QUEEN]
        assert len(queen_moves) == 26


class TestKingMoves:
    def test_king_center(self):
        """测试王在中心"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[4][4] = "K"
        board[7][7] = "k"
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        king_moves = [m for m in moves if m.piece.piece_type == PieceType.KING and m.piece.color == ChessColor.WHITE]
        assert len(king_moves) == 8

    def test_castling_rights(self):
        """测试王车易位"""
        board = [
            ["r", "", "", "", "k", "", "", "r"],
            ["", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", ""],
            ["R", "", "", "", "K", "", "", "R"],
        ]
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        castlings = [m for m in moves if m.is_castling]
        assert len(castlings) == 2


class TestMultiverseContext:
    def test_no_synthetic_time_moves_without_timeline_state(self):
        """没有真实 Timeline 棋盘时，不再凭空生成旧式时间传送。"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[4][4] = "R"
        board[0][0] = "K"
        board[7][7] = "k"
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=4)

        moves = MoveGenerator(pos).generate_all()

        assert all(move.is_spatial for move in moves)
        assert not any(move.is_branching or move.is_cross_timeline for move in moves)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
