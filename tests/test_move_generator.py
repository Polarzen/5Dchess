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
        board[4][4] = "P"  # 白兵 e4 → row 4, col 4
        board[3][5] = "p"  # 黑兵 f4 → row 3, col 5 (白兵向上斜吃目标)
        board[0][0] = "K"  # 白王
        board[7][7] = "k"  # 黑王
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        captures = [m for m in moves if m.captured]
        assert len(captures) >= 1  # e4xf5 (白兵在row4向上斜吃到row3)

    def test_promotion(self):
        """测试兵升变"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[0][4] = ""  # 确保目标格为空
        board[1][4] = "P"  # 白兵在row 1 (一步到row 0升变)
        board[7][0] = "K"  # 白王
        board[0][7] = "k"  # 黑王
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        promotions = [m for m in moves if m.promotion]
        assert len(promotions) == 4  # 4种升变


class TestKnightMoves:
    def test_knight_center(self):
        """测试马在中心"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[4][4] = "N"  # 白马在e4
        board[0][0] = "K"  # 白王
        board[7][7] = "k"  # 黑王
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        knight_moves = [m for m in moves if m.piece.piece_type == PieceType.KNIGHT]
        assert len(knight_moves) == 8  # 中心马有8个走法


class TestSlidingMoves:
    def test_rook_open_file(self):
        """测试车在开放线"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[4][4] = "R"  # 白车在e4
        board[0][0] = "K"  # 白王
        board[7][7] = "k"  # 黑王
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        rook_moves = [m for m in moves if m.piece.piece_type == PieceType.ROOK]
        assert len(rook_moves) == 14  # 4方向各3-4格 = 14

    def test_bishop_diagonal(self):
        """测试象在斜线"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[4][4] = "B"  # 白象在e4
        board[0][0] = "K"
        board[7][7] = "k"
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        bishop_moves = [m for m in moves if m.piece.piece_type == PieceType.BISHOP]
        assert len(bishop_moves) == 12  # 4个对角线: NE=3, NW=3, SW=3, SE=3

    def test_queen_center(self):
        """测试后在中心"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[4][4] = "Q"  # 白后在e4
        board[0][0] = "K"
        board[7][7] = "k"
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        queen_moves = [m for m in moves if m.piece.piece_type == PieceType.QUEEN]
        assert len(queen_moves) == 26  # 车14 + 象12


class TestKingMoves:
    def test_king_center(self):
        """测试王在中心"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[4][4] = "K"  # 白王在e4
        board[7][7] = "k"  # 黑王
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        king_moves = [m for m in moves if m.piece.piece_type == PieceType.KING and m.piece.color == ChessColor.WHITE]
        assert len(king_moves) == 8  # 王周围8格

    def test_castling_rights(self):
        """测试王车易位"""
        board = [
            ["r", "", "", "", "k", "", "", "r"],  # 黑方 row 0
            ["", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", ""],
            ["R", "", "", "", "K", "", "", "R"],  # 白方 row 7
        ]
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        castlings = [m for m in moves if m.is_castling]
        assert len(castlings) == 2  # 短易位 + 长易位


class TestTimeMoves:
    def test_time_travel_moves(self):
        """测试时间旅行走子生成"""
        board = [["" for _ in range(8)] for _ in range(8)]
        board[4][4] = "P"  # 白兵在e4
        board[0][0] = "K"  # 白王
        board[7][7] = "k"  # 黑王
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=5)
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        branching = [m for m in moves if m.is_branching]
        # time_point=5, 所以可以向t=0,1,2,3,4移动
        assert len(branching) >= 1  # 兵可以向过去走


if __name__ == "__main__":
    pytest.main([__file__, "-v"])