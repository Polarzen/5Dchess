"""
5D Chess - 困难AI（深搜索 + 开局库）
"""
from src.utils.constants import ChessColor, AIDifficulty
from src.ai.base import AIPlayer
from src.ai.alpha_beta import AlphaBetaAI
from src.ai.opening_book import OpeningBook
from src.engine.move_generator import Move
from src.engine.engine import FiveDEngine


class HardAI(AIPlayer):
    """困难AI：Alpha-Beta深搜索 + 开局库"""

    def __init__(self, color: ChessColor, search_depth: int = 4):
        super().__init__(color, AIDifficulty.HARD)
        self.search_depth = search_depth
        self.alpha_beta = AlphaBetaAI(color, search_depth)
        self.opening_book = OpeningBook()

    def choose_move(self, engine: FiveDEngine) -> Move | None:
        """选择最佳走子"""
        self._guard_action_progress(engine)

        # 1. 开局阶段尝试使用开局库
        if engine.move_counter < 10:
            book_move = self.opening_book.lookup(engine.move_history)
            if book_move:
                return book_move

        # 2. Alpha-Beta 深搜索
        return self.alpha_beta.choose_move(engine)

    @property
    def nodes_searched(self) -> int:
        return self.alpha_beta.nodes_searched
