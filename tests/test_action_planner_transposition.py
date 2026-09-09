"""Safety regression coverage for ActionPlanner failed-state transpositions."""

from types import SimpleNamespace

import src.ai.action_planner as action_planner
from src.ai.action_planner import ActionPlanner, ActionSearchBudget
from src.engine import Piece
from src.engine.action_search import ActionSearch
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.move_generator import Move
from src.utils.constants import ChessColor, GameState, PieceType


BOARD = BoardCoord(0, 0, ChessColor.WHITE)
PIECE = Piece(PieceType.ROOK, ChessColor.WHITE)


def _move(destination_x: int) -> Move:
    return Move(
        piece=PIECE,
        source=Square5D(BOARD, 0, 0),
        destination=Square5D(BOARD, destination_x, 0),
    )


class _Manager:
    def __init__(self):
        self.timelines = {}

    def refresh_activity(self) -> None:
        pass


class _FakeState:
    def __init__(self, node: str, *, terminal: str):
        self.node = node
        self.terminal = terminal
        self.game_state = GameState.PLAYING
        self.timeline_manager = _Manager()

    def clone_for_simulation(self):
        return _FakeState(self.node, terminal=self.terminal)

    def _ensure_current_action(self):
        return SimpleNamespace(node=self.node)

    def can_submit_action(self) -> bool:
        return self.node == self.terminal == "win"

    def _resolve_position(self, board):
        return object() if board == BOARD else None

    def get_legal_moves(self, _position):
        if self.node == "root":
            return [_move(1), _move(2)]
        if self.node in {"left", "right"}:
            return [_move(3)]
        return []

    def execute_action_move(self, move: Move) -> bool:
        if self.node == "root" and move.destination.x == 1:
            self.node = "left"
            return True
        if self.node == "root" and move.destination.x == 2:
            self.node = "right"
            return True
        if self.node in {"left", "right"} and move.destination.x == 3:
            self.node = self.terminal
            return True
        return False


def _patch_rules(monkeypatch, terminal: str) -> None:
    def required_boards(action, _timelines):
        if action.node == terminal == "win":
            return set()
        return {BOARD}

    def movable_boards(action, _timelines):
        if action.node == terminal:
            return set()
        return {BOARD}

    monkeypatch.setattr(
        action_planner.ActionRules,
        "required_boards",
        staticmethod(required_boards),
    )
    monkeypatch.setattr(
        action_planner.ActionRules,
        "movable_boards",
        staticmethod(movable_boards),
    )
    monkeypatch.setattr(
        ActionSearch,
        "_state_key",
        staticmethod(lambda state: state.node),
    )


def _budget() -> ActionSearchBudget:
    return ActionSearchBudget(
        max_states=32,
        max_actions=None,
        max_move_depth=8,
        max_seconds=None,
    )


def test_equivalent_exhaustive_dead_end_is_expanded_once(monkeypatch):
    _patch_rules(monkeypatch, terminal="dead")

    result = ActionPlanner(_budget()).search(_FakeState("root", terminal="dead"))

    assert result.termination_reason is None
    assert result.candidates == ()
    # root, left, first dead, right. The second equivalent dead state is a hit
    # and is not counted as another explored state.
    assert result.explored_states == 4
    assert result.failed_state_cache_hits == 1


def test_successful_equivalent_states_are_never_pruned(monkeypatch):
    _patch_rules(monkeypatch, terminal="win")

    result = ActionPlanner(_budget()).search(_FakeState("root", terminal="win"))

    assert result.termination_reason is None
    assert len(result.candidates) == 2
    assert [candidate[0].destination.x for candidate in result.candidates] == [1, 2]
    assert result.failed_state_cache_hits == 0
