"""
5D Chess - PvP 真人对弈模式（同屏热座）
"""
from src.engine.move_generator import Move
from src.engine.engine import FiveDEngine
from src.modes.base import GameModeBase
from src.utils.logger import logger


class PvPMode(GameModeBase):
    """真人对弈模式：白方走 → 黑方走 → 交替"""

    def __init__(self, engine: FiveDEngine = None):
        super().__init__(engine)
        self.selected_piece: tuple[int, int] | None = None
        self.legal_moves_for_selected: list[Move] = []

    def start(self):
        """启动PvP模式"""
        logger.info("PvP模式启动 — 白方先行")
        self.emit("game_started", {"mode": "pvp", "current_turn": "white"})

    def handle_move(self, move: Move) -> bool:
        """处理走子"""
        if not self._is_valid_turn(move):
            logger.warning("非当前方走子")
            return False

        success = self.engine.execute_move(move)
        if success:
            self.emit("move_executed", move)
            self._check_game_over()
        return success

    def select_square(self, x: int, y: int) -> dict:
        """处理棋盘点击，返回操作信息"""
        position = self.engine.get_current_position()
        piece = position.get_piece(x, y)

        if self.selected_piece is None:
            # 选择棋子
            if piece and piece.color == self.engine.current_turn_color:
                self.selected_piece = (x, y)
                all_legal = self.engine.get_legal_moves()
                self.legal_moves_for_selected = [
                    m for m in all_legal
                    if m.from_x == x and m.from_y == y
                ]
                return {
                    "action": "selected",
                    "x": x, "y": y,
                    "valid_moves": [
                        {"x": m.to_x, "y": m.to_y, "is_branching": m.is_branching,
                         "timeline_id": m.to_timeline_id, "time": m.to_time}
                        for m in self.legal_moves_for_selected
                    ],
                }
            return {"action": "invalid", "reason": "不是你的棋子"}
        else:
            # 尝试走子
            fx, fy = self.selected_piece
            move = self._find_move(fx, fy, x, y)
            self.selected_piece = None
            self.legal_moves_for_selected = []

            if move:
                success = self.handle_move(move)
                return {
                    "action": "moved" if success else "invalid",
                    "move": {
                        "from": [move.from_x, move.from_y],
                        "to": [move.to_x, move.to_y],
                        "notation": move.to_notation(),
                    },
                    "success": success,
                }
            else:
                # 可能是重新选择
                if piece and piece.color == self.engine.current_turn_color:
                    self.selected_piece = (x, y)
                    all_legal = self.engine.get_legal_moves()
                    self.legal_moves_for_selected = [
                        m for m in all_legal
                        if m.from_x == x and m.from_y == y
                    ]
                    return {"action": "selected", "x": x, "y": y}
                return {"action": "invalid", "reason": "非法走子"}

    def _find_move(self, fx: int, fy: int, tx: int, ty: int) -> Move | None:
        """在合法走子中找到匹配的走子"""
        for move in self.legal_moves_for_selected:
            if move.to_x == tx and move.to_y == ty:
                return move
        return None

    def _is_valid_turn(self, move: Move) -> bool:
        return move.piece.color == self.engine.current_turn_color

    def _check_game_over(self):
        """检查游戏是否结束"""
        state = self.engine.game_state
        if state in (state.CHECKMATE, state.STALEMATE, state.DRAW):
            self.emit("game_over", {"result": state.name})

    def get_board_state(self) -> dict:
        """获取当前棋盘状态"""
        pos = self.engine.get_current_position()
        return {
            "board": pos.board,
            "turn": pos.turn.value,
            "timeline_id": pos.timeline_id,
            "time_point": pos.time_point,
            "legal_moves": [
                {"from": (m.from_x, m.from_y), "to": (m.to_x, m.to_y),
                 "is_branching": m.is_branching, "to_timeline": m.to_timeline_id,
                 "to_time": m.to_time}
                for m in self.engine.get_legal_moves()
            ],
            "selected_square": self.selected_piece,
            **self.engine.get_game_summary(),
        }