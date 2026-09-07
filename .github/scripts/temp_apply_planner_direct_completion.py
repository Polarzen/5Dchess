from pathlib import Path

PLANNER = Path("src/ai/action_planner.py")
TEST = Path("tests/test_action_planner_direct_completion.py")

old = '''            for move in sorted(
                required_moves,
                key=lambda candidate: _required_move_sort_key(candidate, required),
            ):
                if tracker.check(depth):
                    return found_completion
                child = state.clone_for_simulation()
                if not child.execute_action_move(move):
                    continue
                if self._dfs(
                    child,
                    path + (MoveSpec.from_move(move),),
                    depth + 1,
                    tracker,
                    candidates,
                    failed_states,
                ):
                    found_completion = True

            ordered_boards = tuple(optional_boards)
'''

new = '''            ordered_required_moves = sorted(
                required_moves,
                key=lambda candidate: _required_move_sort_key(candidate, required),
            )

            # A progress=2 Move can advance both required Present boards at once.
            # Probe only those few candidates through the canonical submission
            # predicate before descending. A royal-unsafe progress=2 Move can
            # otherwise open a huge optional-move subtree and consume the whole
            # budget before a later one-Move legal Action is even inspected.
            #
            # This is ordering only: every Move remains in the search, and a
            # prebuilt child is reused below instead of executing the Move twice.
            prepared_required_moves = []
            for move in ordered_required_moves:
                if tracker.check(depth):
                    return found_completion
                child = None
                direct_completion = False
                if _required_board_progress(move, required) == 2:
                    child = state.clone_for_simulation()
                    if not child.execute_action_move(move):
                        continue
                    child_required = set(ActionRules.required_boards(
                        child._ensure_current_action(),
                        child.timeline_manager.timelines,
                    ))
                    if not child_required:
                        if tracker.check_time():
                            return found_completion
                        direct_completion = child.can_submit_action()
                        if tracker.check_time():
                            return found_completion
                prepared_required_moves.append((direct_completion, move, child))

            # Python's sort is stable, so non-direct candidates retain the exact
            # deterministic order produced by _required_move_sort_key.
            prepared_required_moves.sort(key=lambda item: not item[0])

            for _, move, child in prepared_required_moves:
                if tracker.check(depth):
                    return found_completion
                if child is None:
                    child = state.clone_for_simulation()
                    if not child.execute_action_move(move):
                        continue
                if self._dfs(
                    child,
                    path + (MoveSpec.from_move(move),),
                    depth + 1,
                    tracker,
                    candidates,
                    failed_states,
                ):
                    found_completion = True

            ordered_boards = tuple(optional_boards)
'''

text = PLANNER.read_text(encoding="utf-8")
if text.count(old) != 1:
    raise SystemExit(f"expected exactly one planner block, found {text.count(old)}")
PLANNER.write_text(text.replace(old, new), encoding="utf-8")

TEST.write_text('''"""Regression for direct two-board completion priority under a tight budget."""

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
''', encoding="utf-8")
