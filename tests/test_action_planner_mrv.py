"""Focused coverage for required-board MRV preparation."""

from collections import Counter

import pytest

import src.ai.action_planner as action_planner
from src.ai.action_planner import ActionPlanner, ActionSearchBudget
from src.engine.action_search import ActionSearch
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.move_generator import Move
from src.engine.piece import Piece
from src.utils.constants import ChessColor, GameState, PieceType


PIECE = Piece(PieceType.ROOK, ChessColor.WHITE)
BOARD_C = BoardCoord(0, 0, ChessColor.WHITE)
BOARD_B = BoardCoord(1, 0, ChessColor.WHITE)
BOARD_A = BoardCoord(2, 0, ChessColor.WHITE)
BOARD_D = BoardCoord(3, 0, ChessColor.WHITE)
BOARD_OPTIONAL = BoardCoord(-1, 0, ChessColor.WHITE)


class _Manager:
    def __init__(self):
        self.timelines = {}

    def refresh_activity(self):
        pass


class _Clock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class _MRVGraphEngine:
    """Minimal canonical API graph with several required source boards."""

    def __init__(
        self,
        graph,
        *,
        node="root",
        terminals=(),
        calls=None,
        call_order=None,
        clock=None,
        interrupt_once=0.0,
    ):
        self.graph = graph
        self.node = node
        self.terminals = frozenset(terminals)
        self.calls = calls if calls is not None else Counter()
        self.call_order = call_order if call_order is not None else []
        self.clock = clock
        self.interrupt_once = interrupt_once
        self.interrupt_state = {"fired": False}
        self.game_state = GameState.PLAYING
        self.current_turn_color = ChessColor.WHITE
        self.timeline_manager = _Manager()

    def clone_for_simulation(self):
        clone = _MRVGraphEngine(
            self.graph,
            node=self.node,
            terminals=self.terminals,
            calls=self.calls,
            call_order=self.call_order,
            clock=self.clock,
            interrupt_once=self.interrupt_once,
        )
        clone.interrupt_state = self.interrupt_state
        return clone

    def _ensure_current_action(self):
        return self.node

    def _resolve_position(self, board):
        return board

    def get_legal_moves(self, board):
        self.calls[(self.node, board)] += 1
        self.call_order.append((self.node, board))
        if self.clock is not None and not self.interrupt_state["fired"]:
            self.interrupt_state["fired"] = True
            self.clock.advance(self.interrupt_once)
        return [
            _move(board, destination, index)
            for destination, target, index in self.graph.get(
                (self.node, board),
                (),
            )
        ]

    def execute_action_move(self, move):
        for destination, target, index in self.graph.get(
            (self.node, move.source.board),
            (),
        ):
            if (
                move.destination.board == destination
                and move.destination.x == index
            ):
                self.node = target
                return True
        return False

    def can_submit_action(self):
        return self.node in self.terminals


def _move(source, destination, index):
    return Move(
        piece=PIECE,
        source=Square5D(source, 0, 0),
        destination=Square5D(destination, index, 0),
    )


def _root_graph(*, include_optional=False):
    graph = {
        ("root", BOARD_A): [
            (BOARD_A, "a1", 1),
            (BOARD_A, "a2", 2),
        ],
        ("root", BOARD_B): [(BOARD_B, "b", 3)],
        ("root", BOARD_C): [(BOARD_D, "c", 4)],
        ("root", BOARD_D): [],
    }
    terminals = {"a1", "a2", "b", "c"}
    movable = {BOARD_A, BOARD_B, BOARD_C, BOARD_D}
    if include_optional:
        graph[("root", BOARD_OPTIONAL)] = [
            (BOARD_OPTIONAL, "optional", 5),
        ]
        terminals.add("optional")
        movable.add(BOARD_OPTIONAL)
    return graph, terminals, movable


def _patch_rules(monkeypatch, *, movable, terminals):
    required = {BOARD_A, BOARD_B, BOARD_C, BOARD_D}

    def required_boards(action, _timelines):
        return set() if action in terminals else required

    def movable_boards(action, _timelines):
        return set() if action in terminals else movable

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


def _planner(**budget):
    values = {
        "max_states": 1024,
        "max_actions": 24,
        "max_move_depth": 32,
        "max_seconds": 5.0,
    }
    values.update(budget)
    return ActionPlanner(ActionSearchBudget(**values))


def test_mrv_keeps_all_required_moves_and_zero_outgoing_board_last(monkeypatch):
    graph, terminals, movable = _root_graph()
    _patch_rules(monkeypatch, movable=movable, terminals=terminals)
    engine = _MRVGraphEngine(graph, terminals=terminals)

    result = _planner().search(engine)

    assert result.termination_reason is None
    assert [
        (candidate[0].source.board, candidate[0].destination.board)
        for candidate in result.candidates
    ] == [
        (BOARD_C, BOARD_D),
        (BOARD_B, BOARD_B),
        (BOARD_A, BOARD_A),
        (BOARD_A, BOARD_A),
    ]
    assert [candidate[0].destination.x for candidate in result.candidates] == [
        4,
        3,
        1,
        2,
    ]
    # The exact envelope runs the shallow probe and the fallback. Each phase
    # prepares every required board once, so no phase repeats a board query.
    assert all(engine.calls[("root", board)] == 2 for board in movable)


def test_optional_boards_stay_lazy_after_prepared_required_boards(monkeypatch):
    graph, terminals, movable = _root_graph(include_optional=True)
    _patch_rules(monkeypatch, movable=movable, terminals=terminals)
    engine = _MRVGraphEngine(graph, terminals=terminals)

    result = _planner().search(engine)

    assert result.candidates
    assert result.candidates[0][0].source.board == BOARD_C
    assert result.termination_reason is None
    assert engine.calls[("root", BOARD_OPTIONAL)] == 2
    first_optional = engine.call_order.index(("root", BOARD_OPTIONAL))
    assert first_optional > max(
        index
        for index, item in enumerate(engine.call_order[:first_optional])
        if item[0] == "root" and item[1] in {
            BOARD_A,
            BOARD_B,
            BOARD_C,
            BOARD_D,
        }
    )
    assert all(engine.calls[("root", board)] == 2 for board in {
        BOARD_A,
        BOARD_B,
        BOARD_C,
        BOARD_D,
    })


def test_local_preparation_interrupt_remains_unresolved_and_uncached(monkeypatch):
    graph, terminals, movable = _root_graph()
    _patch_rules(monkeypatch, movable=movable, terminals=terminals)
    clock = _Clock()
    monkeypatch.setattr(action_planner.time, "monotonic", clock.monotonic)
    engine = _MRVGraphEngine(
        graph,
        terminals=terminals,
        clock=clock,
        interrupt_once=1.1,
    )

    result = ActionPlanner(ActionSearchBudget(
        max_states=1024,
        max_actions=24,
        max_move_depth=32,
        max_seconds=5.0,
    )).search(engine)

    assert result.candidates
    assert result.termination_reason is None
    assert result.failed_state_cache_hits == 0


def test_global_preparation_interrupt_does_not_cache_partial_state(monkeypatch):
    graph, terminals, movable = _root_graph()
    _patch_rules(monkeypatch, movable=movable, terminals=terminals)
    clock = _Clock()
    monkeypatch.setattr(action_planner.time, "monotonic", clock.monotonic)
    engine = _MRVGraphEngine(
        graph,
        terminals=terminals,
        clock=clock,
        interrupt_once=5.1,
    )

    result = _planner().search(engine)

    assert result.candidates == ()
    assert result.termination_reason == "time_budget"
    assert result.failed_state_cache_hits == 0


def test_mrv_dispatch_is_enabled_for_the_exact_production_envelope(monkeypatch):
    graph, terminals, movable = _root_graph()
    _patch_rules(monkeypatch, movable=movable, terminals=terminals)
    engine = _MRVGraphEngine(graph, terminals=terminals)
    calls = {"count": 0}
    original = action_planner._prepare_required_legal_moves

    def spy(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        action_planner,
        "_prepare_required_legal_moves",
        spy,
    )

    result = _planner().search(engine)

    assert result.candidates
    assert calls["count"] > 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_states", 1023),
        ("max_actions", 23),
        ("max_move_depth", 31),
        ("max_seconds", 4.999),
    ],
)
def test_mrv_dispatch_is_excluded_when_any_envelope_field_differs(
    monkeypatch,
    field,
    value,
):
    graph, terminals, movable = _root_graph()
    _patch_rules(monkeypatch, movable=movable, terminals=terminals)
    engine = _MRVGraphEngine(graph, terminals=terminals)
    calls = {"count": 0}
    original = action_planner._prepare_required_legal_moves

    def spy(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        action_planner,
        "_prepare_required_legal_moves",
        spy,
    )
    budget = {
        "max_states": 1024,
        "max_actions": 24,
        "max_move_depth": 32,
        "max_seconds": 5.0,
    }
    budget[field] = value

    _planner(**budget).search(engine)

    assert calls["count"] == 0
