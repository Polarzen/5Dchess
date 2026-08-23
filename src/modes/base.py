"""
5D Chess - 游戏模式抽象基类
"""
from abc import ABC, abstractmethod
from src.engine.engine import FiveDEngine
from src.engine.move_generator import Move
from src.utils.constants import GameState


class GameModeBase(ABC):
    """游戏模式抽象基类"""

    def __init__(self, engine: FiveDEngine = None):
        self.engine = engine or FiveDEngine()
        self._callbacks: dict[str, list[callable]] = {}

    @abstractmethod
    def handle_move(self, move: Move) -> bool:
        """处理走子"""
        ...

    @abstractmethod
    def start(self):
        """启动模式"""
        ...

    def on(self, event: str, callback: callable):
        """注册事件回调"""
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def emit(self, event: str, *args, **kwargs):
        """触发事件"""
        for cb in self._callbacks.get(event, []):
            cb(*args, **kwargs)

    def get_state(self) -> dict:
        """获取当前模式状态"""
        return {
            "mode": self.__class__.__name__,
            "game_state": self.engine.game_state.name,
            **self.engine.get_game_summary(),
        }