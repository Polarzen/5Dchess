"""Regression for direct two-board completion priority under a tight budget."""

from src.ai.action_planner import ActionPlanner, ActionSearchBudget
from src.engine.action import ActionRules
from src.engine.action_search import ActionSearch
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.move_generator import Move
from src.engine.piece import Piece
from src.utils.constants import ChessColor, GameState, PieceType


REQUIRED_A = BoardCoord(0, 0, ChessColor.WHITE)
REQUIRED_B = BoardCoord(1, 0, ChessColor.WHITE)


def _king_move(destination_x: int) -> Move:
    return Move(
        piece=Piece(PieceType.KING, ChessColor.WHITE),
        source=Square5D(REQUIRED_A, 1, 3),
        destination=Square5D(REQUIRED_B, destination_x, 4),
    )


class _FakeTimelineManager:
    def __init__(self):
        self.timelines = {}

    def refresh_activity(self):
        return None


class _FakeEngine:
    def __init__(self, label="root"):
        self.label = label
        self.game_state = GameState.PLAYING
        self.current_turn_color = ChessColor.WHITE
        self.timeline_manager = _FakeTimelineManager()

    def clone_for_simulation(self):
        return _FakeEngine(self.label)

    def _ensure_current_action(self):
        return self.label

    def _resolve_position(self, board):
        return board

    def get_legal_moves(self, position):
        if self.label != "root" or position != REQUIRED_A:
            return []
        return [_king_move(0), _king_move(1)]

    def execute_action_move(self, move):
        self.label = "safe" if move.destination.x == 1 else "unsafe"
        return True

    def can_submit_action(self):
        return self.label == "safe"


def test_direct_submit_candidate_is_found_before_unsafe_progress2_dead_end(monkeypatch):
    required = (REQUIRED_A, REQUIRED_B)
    monkeypatch.setattr(
        ActionRules,
        "required_boards",
        staticmethod(lambda action, timelines: required if action == "root" else ()),
    )
    monkeypatch.setattr(
        ActionRules,
        "movable_boards",
        staticmethod(lambda action, timelines: required if action == "root" else ()),
    )
    monkeypatch.setattr(
        ActionSearch,
        "_state_key",
        staticmethod(lambda state: (state.label,)),
    )

    result = ActionPlanner(ActionSearchBudget(
        max_states=2,
        max_actions=1,
        max_move_depth=4,
        max_seconds=None,
    )).search(_FakeEngine())

    assert result.candidates
    assert result.candidates[0][0].destination.x == 1
