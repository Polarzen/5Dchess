"""
5D Chess - AI 模块测试
"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai import RandomAI, AlphaBetaAI, HardAI, Evaluator, create_ai
from src.engine import FiveDEngine, Position
from src.utils.constants import ChessColor, AIDifficulty


class TestAIFactory:
    def test_create_easy_ai(self):
        ai = create_ai("easy", ChessColor.BLACK)
        assert isinstance(ai, RandomAI)
        assert ai.color == ChessColor.BLACK

    def test_create_medium_ai(self):
        ai = create_ai("medium", ChessColor.WHITE)
        assert isinstance(ai, AlphaBetaAI)
        assert ai.search_depth == 2

    def test_create_hard_ai(self):
        ai = create_ai("hard", ChessColor.BLACK)
        assert isinstance(ai, HardAI)
        assert ai.search_depth == 4


class TestRandomAI:
    def test_choose_move(self):
        engine = FiveDEngine()
        ai = RandomAI(ChessColor.BLACK)
        # 先让白方走一步
        white_moves = engine.get_legal_moves()
        engine.execute_move(white_moves[0])
        # 黑方AI走子
        move = ai.choose_move(engine)
        assert move is not None
        assert move.piece.color == ChessColor.BLACK


class TestAlphaBetaAI:
    def test_choose_move(self):
        engine = FiveDEngine()
        ai = AlphaBetaAI(ChessColor.BLACK, search_depth=1)
        white_moves = engine.get_legal_moves()
        engine.execute_move(white_moves[0])
        move = ai.choose_move(engine)
        assert move is not None
        assert move.piece.color == ChessColor.BLACK

    def test_depth_2(self):
        engine = FiveDEngine()
        ai = AlphaBetaAI(ChessColor.WHITE, search_depth=2)
        move = ai.choose_move(engine)
        assert move is not None
        assert move.piece.color == ChessColor.WHITE
        assert ai.nodes_searched > 0


class TestEvaluator:
    def test_initial_evaluation(self):
        pos = Position.initial()
        evaluator = Evaluator()
        score = evaluator.evaluate(pos)
        # 初始局面应该接近0（对称）
        assert abs(score) < 5.0

    def test_material_advantage(self):
        # 白方多半子
        board = [["" for _ in range(8)] for _ in range(8)]
        board[0][4] = "k"  # 黑王
        board[7][4] = "K"  # 白王
        board[4][4] = "Q"  # 白后
        pos = Position(board=board, turn=ChessColor.WHITE, timeline_id=0, time_point=0)
        evaluator = Evaluator()
        score = evaluator.evaluate(pos, ChessColor.WHITE)
        assert score > 5.0  # 白方大优


class TestHardAI:
    def test_choose_move(self):
        engine = FiveDEngine()
        ai = HardAI(ChessColor.WHITE, search_depth=2)
        move = ai.choose_move(engine)
        assert move is not None
        assert move.piece.color == ChessColor.WHITE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])