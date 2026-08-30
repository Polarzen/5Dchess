"""
5D Chess - AI 基类
"""
from abc import ABC, abstractmethod
from src.utils.constants import ChessColor, AIDifficulty
from src.engine.move_generator import Move
from src.engine.engine import FiveDEngine
from src.ai.action_planner import (
    AIActionPlan,
    ActionSearchBudget,
    resolve_move_spec,
)


class AIPlayer(ABC):
    """AI 玩家抽象基类"""

    def __init__(
        self,
        color: ChessColor,
        difficulty: AIDifficulty,
        budget: ActionSearchBudget | None = None,
    ):
        self.color = color
        self.difficulty = difficulty
        self.budget = budget

    def _guard_action_progress(self, engine: FiveDEngine) -> None:
        """Fail loudly instead of letting an AI Action spin indefinitely.

        A normal compatibility-path AI should consume required Present boards
        and auto-submit.  If one Action accumulates far more Moves than the
        configured timeline capacity, something is no longer making useful
        progress (typically repeated branching or a caller/selection bug).
        Raising here is safe because it happens before the next state mutation;
        Web callers already surface the exception as an explicit AI error.
        """
        action = engine.current_action
        if (
            engine.current_turn_color != self.color
            or action is None
            or action.submitted
        ):
            return

        move_limit = max(16, engine.max_timelines + 8)
        if len(action.moves) >= move_limit:
            raise RuntimeError(
                "AI Action safety guard reached "
                f"{move_limit} moves without submission; "
                "automatic execution stopped to prevent a loop"
            )

    @abstractmethod
    def plan_action(self, engine: FiveDEngine) -> AIActionPlan:
        """Plan one complete canonical Action without mutating ``engine``."""
        ...

    def choose_move(self, engine: FiveDEngine) -> Move | None:
        """Compatibility shim returning the first exactly resolved Move.

        New callers should consume :meth:`plan_action` and apply the complete
        Action.  Existing board-local callers can still execute this first
        Move through the engine's compatibility entry point.
        """
        self._guard_action_progress(engine)
        plan = self.plan_action(engine)
        if not plan.moves:
            return None
        return resolve_move_spec(engine, plan.moves[0])

    @property
    def name(self) -> str:
        return f"AI ({self.difficulty.value})"

    def __repr__(self) -> str:
        return f"AIPlayer({self.color.value}, {self.difficulty.value})"
