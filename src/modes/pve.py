"""
5D Chess - PvE 人机对弈模式
"""
from copy import deepcopy
import threading
from typing import Any

from src.engine.move_generator import Move
from src.engine.engine import FiveDEngine
from src.modes.base import GameModeBase
from src.ai import create_ai, AIPlayer
from src.ai.action_planner import (
    AIActionPlan,
    ActionPlanningError,
    StaleActionPlanError,
    apply_action_plan,
    engine_state_signature,
)
from src.utils.constants import ChessColor, GameState
from src.utils.logger import logger


class PvEMode(GameModeBase):
    """人机对弈模式：玩家完成一个 Action 后，再由 AI 完成一个 Action。"""

    def __init__(self, engine: FiveDEngine = None,
                 player_color: ChessColor = ChessColor.WHITE,
                 ai_difficulty: str = "medium"):
        super().__init__(engine)
        self.player_color = player_color
        self.ai_difficulty = ai_difficulty
        self.ai_color = player_color.opposite()
        self.ai: AIPlayer = create_ai(ai_difficulty, self.ai_color)
        # All access which can mutate the live engine is serialized here. AI
        # planning deliberately happens outside this lock on a deep copy.
        self._lock = threading.RLock()
        self._ai_thinking = False
        self._ai_warning: str | None = None
        self._ai_error: str | None = None

    def start(self):
        """启动 PvE 模式。

        The Web client explicitly requests the opening AI Action after it has
        installed the session. Keeping start side-effect free avoids a race
        between session setup and AI mutation.
        """
        with self._lock:
            logger.info(
                f"PvE模式启动 — 玩家: {self.player_color.value}, "
                f"AI: {self.ai_difficulty}"
            )
            self.emit("game_started", {
                "mode": "pve",
                "player_color": self.player_color.value,
                "ai_difficulty": self.ai_difficulty,
            })

    def execute_player_action_move(self, move: Move) -> bool:
        """Apply one player Move to the current Action without submitting it."""
        with self._lock:
            if self.engine.game_state != GameState.PLAYING:
                return False
            if self._ai_thinking:
                return False
            if self.engine.current_turn_color != self.player_color:
                return False
            if move is None or move.piece.color != self.player_color:
                return False

            success = self.engine.execute_action_move(move)
            if success:
                self.emit("player_move_executed", move)
            return success

    def submit_player_action(self) -> bool:
        """Explicitly submit the player's complete current Action."""
        with self._lock:
            if self.engine.game_state != GameState.PLAYING:
                return False
            if self._ai_thinking or self.engine.current_turn_color != self.player_color:
                return False
            if not self.engine.can_submit_action():
                return False
            success = self.engine.submit_action()
            if success:
                self._check_game_over()
            return success

    # Short aliases keep callers which describe the operation as a player
    # move/submit compatible while retaining the explicit Action semantics.
    execute_player_move = execute_player_action_move
    submit_action = submit_player_action

    def handle_player_move(self, move: Move) -> bool:
        """Compatibility entry point for one player Action Move.

        PvE no longer auto-submits or starts a background AI mutation here;
        callers must explicitly submit the Action first.
        """
        return self.execute_player_action_move(move)

    def _result(
        self,
        success: bool,
        *,
        moves: tuple[Move, ...] = (),
        error: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        return {
            "success": success,
            "moves": moves,
            "submitted": success,
            "warning": self._ai_warning,
            "error": error,
            "error_code": error_code,
        }

    def _failure(self, error: str, error_code: str) -> dict[str, Any]:
        self._ai_error = error
        return self._result(False, error=error, error_code=error_code)

    def execute_ai_action(self) -> dict[str, Any]:
        """Plan and apply exactly one complete AI Action synchronously.

        A snapshot is taken while holding the writer lock, then planning runs
        without the lock. Applying the plan reacquires the lock and lets the
        planner module revalidate the snapshot signature and full sequence.
        ``apply_action_plan`` owns the single canonical submission.
        """
        with self._lock:
            if self.engine.game_state != GameState.PLAYING:
                return self._failure("游戏已结束", "game_over")
            if self._ai_thinking:
                return self._failure("AI 正在思考", "busy")
            if self.engine.current_turn_color != self.ai_color:
                return self._failure("当前不是 AI 回合", "wrong_turn")

            self._ai_thinking = True
            self._ai_warning = None
            self._ai_error = None
            self.emit("ai_thinking", True)

        result: dict[str, Any]
        try:
            # Snapshot construction is part of the serialized read boundary;
            # the potentially expensive plan_action call is not.
            with self._lock:
                snapshot = deepcopy(self.engine)
                snapshot_signature = engine_state_signature(snapshot)

            plan: AIActionPlan = self.ai.plan_action(snapshot)

            with self._lock:
                # This early check gives a stable failure even if an external
                # caller changed the engine while planning. apply_action_plan
                # performs its own authoritative stale/full-legality checks.
                if engine_state_signature(self.engine) != snapshot_signature:
                    raise StaleActionPlanError(
                        "棋局在 AI 思考期间发生变化，计划已失效"
                    )

                history_start = len(self.engine.move_history)
                applied = apply_action_plan(self.engine, plan)
                if applied is None:
                    applied_moves: tuple[Move, ...] = ()
                elif isinstance(applied, bool):
                    # Older planner implementations returned only success;
                    # recover the canonical objects recorded by the engine.
                    applied_moves = tuple(self.engine.move_history[history_start:])
                elif isinstance(applied, Move):
                    applied_moves = (applied,)
                else:
                    applied_moves = tuple(applied)
                    if not all(isinstance(move, Move) for move in applied_moves):
                        applied_moves = tuple(self.engine.move_history[history_start:])

                self._ai_warning = getattr(plan, "warning", None)
                self._ai_error = None
                for move in applied_moves:
                    self.emit("ai_move_executed", move)
                self.emit("ai_action_executed", applied_moves)
                self._check_game_over()
                result = self._result(True, moves=applied_moves)
        except StaleActionPlanError:
            with self._lock:
                result = self._failure(
                    "棋局在 AI 思考期间发生变化，计划已失效，请重试",
                    "stale_plan",
                )
        except ActionPlanningError:
            with self._lock:
                result = self._failure(
                    "AI 未能规划完整合法 Action",
                    "plan_failed",
                )
        except Exception:
            # Keep response details safe while preserving diagnostics in logs.
            logger.exception("AI Action 执行失败")
            with self._lock:
                result = self._failure("AI Action 执行失败，请重试", "action_failed")
        finally:
            with self._lock:
                self._ai_thinking = False
                self.emit("ai_thinking", False)

        return result

    def _request_ai_move(self):
        """Compatibility shim for older GUI callers.

        It is synchronous and uses the same canonical path; PvE's normal Web
        flow calls ``execute_ai_action`` explicitly instead of scheduling a
        mutating worker thread.
        """
        return self.execute_ai_action()

    def get_board_state(self) -> dict:
        """获取当前棋盘状态"""
        with self._lock:
            pos = self.engine.get_current_position()
            return {
                "board": pos.board,
                "turn": pos.turn.value,
                "timeline_id": pos.timeline_id,
                "time_point": pos.time_point,
                "player_color": self.player_color.value,
                "ai_difficulty": self.ai_difficulty,
                "ai_thinking": self._ai_thinking,
                "ai_warning": self._ai_warning,
                "ai_error": self._ai_error,
                "legal_moves": [
                    {"from": (m.from_x, m.from_y), "to": (m.to_x, m.to_y),
                     "is_branching": m.is_branching}
                    for m in self.engine.get_legal_moves()
                ] if self.engine.current_turn_color == self.player_color else [],
                **self.engine.get_game_summary(),
            }

    def handle_move(self, move: Move) -> bool:
        """统一接口 — 等同于 one player Action Move"""
        return self.execute_player_action_move(move)

    def _check_game_over(self):
        """检查游戏是否结束"""
        state = self.engine.game_state
        if state in (state.CHECKMATE, state.STALEMATE, state.DRAW):
            self.emit("game_over", {"result": state.name})
