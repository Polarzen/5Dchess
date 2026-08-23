"""5D Chess AI Module"""
from src.ai.base import AIPlayer
from src.ai.random_ai import RandomAI
from src.ai.alpha_beta import AlphaBetaAI
from src.ai.hard_ai import HardAI
from src.ai.evaluator import Evaluator
from src.ai.opening_book import OpeningBook


def create_ai(difficulty: str, color) -> AIPlayer:
    """工厂函数：根据难度创建AI"""
    from src.utils.constants import ChessColor, AIDifficulty
    diff = AIDifficulty(difficulty)
    if diff == AIDifficulty.EASY:
        return RandomAI(color)
    elif diff == AIDifficulty.MEDIUM:
        return AlphaBetaAI(color, search_depth=2)
    elif diff == AIDifficulty.HARD:
        return HardAI(color, search_depth=4)
    else:
        raise ValueError(f"未知AI难度: {difficulty}")