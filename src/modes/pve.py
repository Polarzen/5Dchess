"""
5D Chess - PvE 人机对弈模式
"""
import threading
from src.engine.move_generator import Move
from src.engine.engine import FiveDEngine
from src.modes.base import GameModeBase
from src.ai import create_ai, AIPlayer
from src.utils.constants import ChessColor, AIDifficulty
from src.utils.logger import logger


class PvEMode(GameModeBase):
    """人机对弈模式：玩家走 → AI走 → 交替"""

    def __init__(self, engine: FiveDEngine = None,
                 player_color: ChessColor = ChessColor.WHITE,
                 ai_difficulty: str = "medium"):
        super().__init__(engine)
        self.player_color = player_color
        self.ai_difficulty = ai_difficulty
        self.ai_color = player_color.opposite()
        self.ai: AIPlayer = create_ai(ai_difficulty, self.ai_color)
        self._ai_thinking = False
        self._ai_thread: threading.Thread | None = None

    def start(self):
        """启动PvE模式"""
        logger.info(f"PvE模式启动 — 玩家: {self.player_color.value}, AI: {self.ai_difficulty}")

        # 如果AI先手，立即走子
        if self.ai_color == ChessColor.WHITE:
            self._request_ai_move()

        self.emit("game_started", {
            "mode": "pve",
            "player_color": self.player_color.value,
            "ai_difficulty": self.ai_difficulty,
        })

    def handle_player_move(self, move: Move) -> bool:
        """处理玩家走子"""
        if move.piece.color != self.player_color:
            return False
        if self._ai_thinking:
            return False

        success = self.engine.execute_move(move)
        if success:
            self.emit("player_move_executed", move)
            self._check_game_over()
            if self.engine.game_state == self.engine.game_state.PLAYING:
                self._request_ai_move()
        return success

    def _request_ai_move(self):
        """异步请求AI走子"""
        self._ai_thinking = True
        self.emit("ai_thinking", True)

        self._ai_thread = threading.Thread(target=self._ai_think, daemon=True)
        self._ai_thread.start()

    def _ai_think(self):
        """AI思考线程"""
        try:
            move = self.ai.choose_move(self.engine)
            if move:
                def apply():
                    success = self.engine.execute_move(move)
                    self._ai_thinking = False
                    if success:
                        self.emit("ai_move_executed", move)
                        self._check_game_over()
                    self.emit("ai_thinking", False)
                # 在主线程中执行（通过回调）
                self.emit("ai_move_ready", move, apply)
            else:
                self._ai_thinking = False
                self.emit("ai_thinking", False)
                logger.warning("AI无合法走子")
        except Exception as e:
            self._ai_thinking = False
            self.emit("ai_thinking", False)
            logger.error(f"AI思考异常: {e}")

    def get_board_state(self) -> dict:
        """获取当前棋盘状态"""
        pos = self.engine.get_current_position()
        return {
            "board": pos.board,
            "turn": pos.turn.value,
            "timeline_id": pos.timeline_id,
            "time_point": pos.time_point,
            "player_color": self.player_color.value,
            "ai_difficulty": self.ai_difficulty,
            "ai_thinking": self._ai_thinking,
            "legal_moves": [
                {"from": (m.from_x, m.from_y), "to": (m.to_x, m.to_y),
                 "is_branching": m.is_branching}
                for m in self.engine.get_legal_moves()
            ] if self.engine.current_turn_color == self.player_color else [],
            **self.engine.get_game_summary(),
        }

    def handle_move(self, move: Move) -> bool:
        """统一接口 — 等同于 handle_player_move"""
        return self.handle_player_move(move)

    def _check_game_over(self):
        """检查游戏是否结束"""
        state = self.engine.game_state
        if state in (state.CHECKMATE, state.STALEMATE, state.DRAW):
            self.emit("game_over", {"result": state.name})