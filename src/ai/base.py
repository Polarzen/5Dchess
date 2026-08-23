"""
5D Chess - AI 基类
"""
from abc import ABC, abstractmethod
from src.utils.constants import ChessColor, AIDifficulty
from src.engine.move_generator import Move
from src.engine.board import Position
from src.engine.engine import FiveDEngine


class AIPlayer(ABC):
    """AI 玩家抽象基类"""

    def __init__(self, color: ChessColor, difficulty: AIDifficulty):
        self.color = color
        self.difficulty = difficulty

    @abstractmethod
    def choose_move(self, engine: FiveDEngine) -> Move | None:
        """选择最佳走子"""
        ...

    @property
    def name(self) -> str:
        return f"AI ({self.difficulty.value})"

    def __repr__(self) -> str:
        return f"AIPlayer({self.color.value}, {self.difficulty.value})"