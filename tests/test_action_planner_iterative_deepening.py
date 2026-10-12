"""Deterministic coverage for the production planner's bounded probe."""

import pytest

import src.ai.action_planner as action_planner
from src.ai.action_planner import (
    AIActionPlan,
    ActionPlanner,
    ActionSearchBudget,
    apply_action_plan,
    engine_state_signature,
)
from src.engine.action_search import ActionSearch
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.move_generator import Move
from src.engine.piece import Piece
from src.utils.constants import ChessColor, GameState, PieceType


BOARD = BoardCoord(0, 0, ChessColor.WHITE)
PIECE = Piece(PieceType.ROOK, ChessColor.WHITE)
TERMINALS = {"win"}


class _Manager:
    def __init__(self):
        self.timelines = {}

    def refresh_activity(self):
        pass


class _GraphEngine:
    """Small canonical-API graph engine used only by these planner tests."""

    def __init__(self, graph, *, node="root", terminals=()):
        self.graph = graph
        self.node = node
        self.terminals = frozenset(terminals)
        self.game_state = GameState.PLAYING
        self.current_turn_color = ChessColor.WHITE
        self.timeline_manager = _Manager()

    def clone_for_simulation(self):
        return _GraphEngine(
            self.graph,
            node=self.node,
            terminals=self.terminals,
        )

    def _ensure_current_action(self):
        return self.node

    def _resolve_position(self, board):
        return board if board == BOARD else None

    def get_legal_moves(self, _position):
        return [
            _move(index, promotion)
            for index, _target, promotion in self.graph.get(self.node, ())
        ]

    def execute_action_move(self, move):
        for index, target, promotion in self.graph.get(self.node, ()):
            if move.destination.x == index and move.promotion == promotion:
                self.node = target
                return True
        return False

    def can_submit_action(self):
        return self.node in self.terminals


class _FakeClock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class _TimedGraphEngine(_GraphEngine):
    def __init__(self, graph, *, clock, tick=None, node="root", terminals=()):
        super().__init__(graph, node=node, terminals=terminals)
        self.clock = clock
        self.tick = tick or (lambda _operation: None)

    def clone_for_simulation(self):
        return _TimedGraphEngine(
            self.graph,
            clock=self.clock,
            tick=self.tick,
            node=self.node,
            terminals=self.terminals,
        )

    def get_legal_moves(self, position):
        self.tick("moves")
        return super().get_legal_moves(position)

    def can_submit_action(self):
        self.tick("submit")
        return super().can_submit_action()


def _move(index, promotion=None):
    return Move(
        piece=PIECE,
        source=Square5D(BOARD, 0, 0),
        destination=Square5D(BOARD, index, 0),
        promotion=promotion,
    )


def _patch_graph_rules(monkeypatch):
    monkeypatch.setattr(
        action_planner.ActionRules,
        "required_boards",
        staticmethod(
            lambda action, _timelines: set() if action in TERMINALS else {BOARD}
        ),
    )
    monkeypatch.setattr(
        action_planner.ActionRules,
        "movable_boards",
        staticmethod(
            lambda action, _timelines: set() if action in TERMINALS else {BOARD}
        ),
    )
    monkeypatch.setattr(
        ActionSearch,
        "_state_key",
        staticmethod(lambda state: state.node),
    )


def _budget(**values):
    return ActionSearchBudget(
        max_states=values.pop("max_states", 256),
        max_actions=values.pop("max_actions", None),
        max_move_depth=values.pop("max_move_depth", 8),
        max_seconds=values.pop("max_seconds", None),
    )


def _planner(graph, *, terminals=TERMINALS, **values):
    return ActionPlanner(_budget(**values)), _GraphEngine(
        graph,
        terminals=terminals,
    )


def _production_planner(graph, *, terminals=TERMINALS, clock=None, tick=None):
    budget = ActionSearchBudget(
        max_states=1024,
        max_actions=24,
        max_move_depth=32,
        max_seconds=5.0,
    )
    if clock is None:
        return ActionPlanner(budget), _GraphEngine(graph, terminals=terminals)
    return ActionPlanner(budget), _TimedGraphEngine(
        graph,
        clock=clock,
        tick=tick,
        terminals=terminals,
    )


def _chain_graph(length):
    graph = {"root": [(0, "n1", None)]}
    for index in range(1, length - 1):
        graph[f"n{index}"] = [(0, f"n{index + 1}", None)]
    graph[f"n{length - 1}"] = [(0, "win", None)]
    graph["win"] = []
    return graph


def _deep_tree_with_shallow_witness(depth=8):
    """Put a direct witness before enough dead states to hit the shared cap."""
    graph = {"root": [(0, "win", None), (1, "deep0", None)], "win": []}
    frontier = ["deep0"]
    for level in range(depth):
        next_frontier = []
        for node_index, node in enumerate(frontier):
            children = [f"dead-{level}-{node_index}-{branch}" for branch in range(3)]
            graph[node] = [(branch, child, None) for branch, child in enumerate(children)]
            next_frontier.extend(children)
        frontier = next_frontier
    for node in frontier:
        graph[node] = []
    return graph


def test_exact_envelope_runs_probe_then_fallback(monkeypatch):
    _patch_graph_rules(monkeypatch)
    clock = _FakeClock()
    first_move = True

    def tick(operation):
        nonlocal first_move
        if operation == "moves" and first_move:
            first_move = False
            clock.advance(1.1)

    monkeypatch.setattr(action_planner.time, "monotonic", clock.monotonic)
    planner, engine = _production_planner(
        _chain_graph(2),
        clock=clock,
        tick=tick,
    )

    result = planner.search(engine)

    assert result.candidates
    assert result.termination_reason is None
    assert engine.node == "root"
    probe, fallback = planner.search_telemetry
    assert probe["phase"] == "probe"
    assert probe["phase_interrupted"] is True
    assert probe["global_reason"] is None
    assert fallback["phase"] == "fallback"
    assert fallback["unique_candidates_delta"] == 1


def test_probe_rejects_completion_crossing_local_deadline(monkeypatch):
    _patch_graph_rules(monkeypatch)
    clock = _FakeClock()
    first_submit = True

    def tick(operation):
        nonlocal first_submit
        if operation == "submit" and first_submit:
            first_submit = False
            clock.advance(1.1)

    monkeypatch.setattr(action_planner.time, "monotonic", clock.monotonic)
    planner, engine = _production_planner(
        {"root": [(0, "win", None)], "win": []},
        clock=clock,
        tick=tick,
    )

    result = planner.search(engine)

    assert result.candidates
    assert result.termination_reason is None
    probe, fallback = planner.search_telemetry
    assert probe["phase_interrupted"] is True
    assert probe["actions_delta"] == 0
    assert fallback["unique_candidates_delta"] == 1


def test_probe_witness_survives_deep_fallback_state_budget(monkeypatch):
    _patch_graph_rules(monkeypatch)
    clock = _FakeClock()
    monkeypatch.setattr(action_planner.time, "monotonic", clock.monotonic)
    planner, engine = _production_planner(
        _deep_tree_with_shallow_witness(),
        clock=clock,
    )

    result = planner.search(engine)

    assert len(result.candidates) == 1
    assert result.candidates[0][0].destination.x == 0
    assert result.termination_reason == "state_budget"
    probe, fallback = planner.search_telemetry
    assert probe["unique_candidates_delta"] == 1
    assert fallback["unique_candidates_delta"] == 0
    assert result.explored_states == 1024


def test_simultaneous_local_and_global_expiry_prefers_global(monkeypatch):
    _patch_graph_rules(monkeypatch)
    clock = _FakeClock()

    def tick(operation):
        if operation == "moves":
            clock.advance(5.0)

    monkeypatch.setattr(action_planner.time, "monotonic", clock.monotonic)
    planner, engine = _production_planner(
        _chain_graph(2),
        clock=clock,
        tick=tick,
    )

    result = planner.search(engine)

    assert not result.candidates
    assert result.termination_reason == "time_budget"
    assert len(planner.search_telemetry) == 1
    record = planner.search_telemetry[0]
    assert record["phase_interrupted"] is False
    assert record["global_reason"] == "time_budget"


def test_exact_action_cap_stops_with_shared_budget(monkeypatch):
    _patch_graph_rules(monkeypatch)
    graph = {"root": [(index, f"n{index}", None) for index in range(7)]}
    for index in range(7):
        graph[f"n{index}"] = [
            (branch, "win", None) for branch in range(4)
        ]
    graph["win"] = []
    planner, engine = _production_planner(graph)

    result = planner.search(engine)

    assert len(result.candidates) == 24
    assert result.termination_reason == "action_budget"
    assert [row["phase"] for row in planner.search_telemetry] == [
        "probe",
        "fallback",
    ]


def test_rediscovery_is_deduplicated_but_action_accounting_is_retained(monkeypatch):
    _patch_graph_rules(monkeypatch)
    planner, engine = _production_planner(
        {"root": [(0, "win", None)], "win": []},
    )

    result = planner.search(engine)

    assert len(result.candidates) == 1
    probe, fallback = planner.search_telemetry
    assert probe["unique_candidates_delta"] == 1
    assert fallback["unique_candidates_delta"] == 0
    assert probe["actions_delta"] == fallback["actions_delta"] == 1


def test_promotion_is_part_of_exact_candidate_path_key(monkeypatch):
    _patch_graph_rules(monkeypatch)
    planner, engine = _production_planner({
        "root": [
            (0, "win", None),
            (0, "win", None),
            (0, "win", PieceType.QUEEN),
        ],
        "win": [],
    })

    result = planner.search(engine)

    assert len(result.candidates) == 2
    assert {candidate[0].promotion for candidate in result.candidates} == {
        None,
        PieceType.QUEEN,
    }
    assert all(row["unique_candidates_after"] == 2 for row in planner.search_telemetry)


def test_cutoff_reason_is_local_to_probe_and_fallback_can_finish(monkeypatch):
    _patch_graph_rules(monkeypatch)
    planner, engine = _production_planner(_chain_graph(2))

    result = planner.search(engine)

    assert result.candidates
    assert result.termination_reason is None
    probe, fallback = planner.search_telemetry
    assert probe["depth_cutoffs_delta"] > 0
    assert fallback["depth_cutoffs_delta"] == 0
    assert fallback["global_reason"] is None


def test_zero_candidate_cutoff_fallback_is_exhaustive(monkeypatch):
    _patch_graph_rules(monkeypatch)
    planner, engine = _production_planner(
        {"root": [(0, "dead", None)], "dead": []},
        terminals=(),
    )

    result = planner.search(engine)

    assert not result.candidates
    assert result.termination_reason is None
    assert [row["phase"] for row in planner.search_telemetry] == [
        "probe",
        "fallback",
    ]
    assert planner.search_telemetry[-1]["depth_cutoffs_delta"] == 0


def test_non_envelope_budgets_keep_ordinary_search_behavior(monkeypatch):
    _patch_graph_rules(monkeypatch)
    budgets = (
        ActionSearchBudget(max_states=256, max_actions=24, max_move_depth=32, max_seconds=None),
        ActionSearchBudget(max_states=256, max_actions=24, max_move_depth=32, max_seconds=5.1),
        ActionSearchBudget(max_states=256, max_actions=24, max_move_depth=1, max_seconds=None),
        ActionSearchBudget(max_states=256, max_actions=24, max_move_depth=0, max_seconds=None),
        ActionSearchBudget(max_states=0, max_actions=24, max_move_depth=32, max_seconds=None),
        ActionSearchBudget(max_states=256, max_actions=0, max_move_depth=32, max_seconds=None),
        ActionSearchBudget(max_states=256, max_actions=24, max_move_depth=32, max_seconds=0),
    )
    expected_reasons = (
        None,
        None,
        "move_depth_budget",
        "move_depth_budget",
        "state_budget",
        "action_budget",
        "time_budget",
    )

    for budget, expected_reason in zip(budgets, expected_reasons):
        planner = ActionPlanner(budget)
        result = planner.search(_GraphEngine(_chain_graph(2)))
        assert planner.search_telemetry == ()
        assert result.termination_reason == expected_reason


@pytest.mark.parametrize(
    ("field", "near_miss"),
    [
        ("max_seconds", 4.999),
        ("max_states", 1023),
        ("max_actions", 23),
        ("max_move_depth", 31),
    ],
)
def test_each_near_miss_budget_stays_ordinary(monkeypatch, field, near_miss):
    _patch_graph_rules(monkeypatch)
    values = {
        "max_states": 1024,
        "max_actions": 24,
        "max_move_depth": 32,
        "max_seconds": 5.0,
    }
    values[field] = near_miss
    planner = ActionPlanner(ActionSearchBudget(**values))

    result = planner.search(_GraphEngine(_chain_graph(2), terminals=TERMINALS))

    assert result.candidates
    assert result.termination_reason is None
    assert planner.search_telemetry == ()


def test_search_telemetry_is_private_and_immutable(monkeypatch):
    _patch_graph_rules(monkeypatch)
    planner, engine = _production_planner(_chain_graph(2))

    planner.search(engine)

    assert not hasattr(planner, "search_iterative_deepening")
    assert not hasattr(planner, "search_hybrid")
    assert isinstance(planner.search_telemetry, tuple)
    with pytest.raises(TypeError):
        planner.search_telemetry[0]["phase"] = "mutated"


def test_exact_envelope_result_replays_canonically_without_mutating_source(
    monkeypatch,
):
    from src.engine.engine import FiveDEngine

    clock = _FakeClock()
    monkeypatch.setattr(action_planner.time, "monotonic", clock.monotonic)
    engine = FiveDEngine()
    before = engine_state_signature(engine)
    planner = ActionPlanner(ActionSearchBudget(
        max_states=1024,
        max_actions=24,
        max_move_depth=32,
        max_seconds=5.0,
    ))

    result = planner.search(engine)

    assert result.candidates
    assert [row["phase"] for row in planner.search_telemetry] == [
        "probe",
        "fallback",
    ]
    assert planner.search_telemetry[0]["depth_cutoffs_delta"] > 0
    assert engine_state_signature(engine) == before
    plan = AIActionPlan(
        color=engine.current_turn_color,
        moves=result.candidates[0],
        start_signature=before,
    )
    replay = engine.clone_for_simulation()
    assert apply_action_plan(replay, plan)
    assert engine_state_signature(engine) == before
