"""
5D Chess - 简单AI（随机合法走子）
"""
import random
from src.utils.constants import ChessColor, AIDifficulty
from src.ai.base import AIPlayer
from src.engine.move_generator import Move
from src.engine.engine import FiveDEngine


class RandomAI(AIPlayer):
    """简单AI：随机选择合法走子"""

    def __init__(self, color: ChessColor):
        super().__init__(color, AIDifficulty.EASY)

    def choose_move(self, engine: FiveDEngine) -> Move | None:
        moves = engine.get_legal_moves()
        if not moves:
            return None
        return random.choice(moves)