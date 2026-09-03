"""Regression coverage for canonical Action-level AI and PvE integration."""
from __future__ import annotations

from copy import deepcopy
import threading
import time

import pytest

from src.ai import (
    AIActionPlan,
    ActionApplicationError,
    ActionPlanner,
    ActionPlanningError,
    ActionSearchBudget,
    AlphaBetaAI,
    HardAI,
    MoveSpec,
    RandomAI,
    StaleActionPlanError,
    apply_action_plan,
    engine_state_signature,
)
from src.engine import (
    ActionRules,
    BoardCoord,
    FiveDEngine,
    Piece,
    Position,
    Square5D,
    Timeline,
)
from src.modes.pve import PvEMode
from src.utils.constants import ChessColor, PieceType
from src.web.app import _game_session, app


FAST_BUDGET = ActionSearchBudget(
    max_states=256,
    max_actions=8,
    max_move_depth=8,
    max_seconds=1.0,
)


def _advance_one_action(engine: FiveDEngine) -> None:
    move = next(
        move for move in engine.get_legal_moves()
        if move.from_x == 4 and move.from_y == 6 and move.to_y == 4
    )
    assert engine.execute_action_move(move)
    assert engine.submit_action()


def _empty_position(timeline_id: int, time_point: int) -> Position:
    board = [["" for _ in range(8)] for _ in range(8)]
    board[7][7] = "K"
    board[0][7] = "k"
    return Position(
        board=board,
        turn=ChessColor.WHITE if time_point % 2 == 0 else ChessColor.BLACK,
        timeline_id=timeline_id,
        time_point=time_point,
        unmoved_pawns=set(),
    )


def _reset_white_action(engine: FiveDEngine) -> None:
    engine.current_turn_color = ChessColor.WHITE
    engine.action_history = []
    engine.current_action = ActionRules.begin(
        ChessColor.WHITE,
        engine.timeline_manager.timelines,
    )


def _two_required_boards_engine() -> FiveDEngine:
    engine = FiveDEngine()
    manager = engine.timeline_manager
    main = manager.get_timeline(0)
    main.positions.clear()
    rook = Piece(PieceType.ROOK, ChessColor.WHITE)
    first = _empty_position(0, 0)
    first.set_piece(0, 6, rook)
    main.add_position(first)
    other = Timeline(timeline_id=1, owner=ChessColor.WHITE)
    second = _empty_position(1, 0)
    second.set_piece(1, 6, rook)
    other.add_position(second)
    manager.timelines[1] = other
    manager.refresh_activity()
    _reset_white_action(engine)
    return engine


def _branching_engine() -> FiveDEngine:
    engine = FiveDEngine()
    main = engine.timeline_manager.get_timeline(0)
    main.positions.clear()
    for time_point in range(3):
        position = _empty_position(0, time_point)
        if time_point == 2:
            position.set_piece(3, 4, Piece(PieceType.ROOK, ChessColor.WHITE))
        main.add_position(position)
    engine.timeline_manager.refresh_activity()
    _reset_white_action(engine)
    return engine


def _cross_timeline_engine() -> FiveDEngine:
    engine = FiveDEngine()
    manager = engine.timeline_manager
    main = manager.get_timeline(0)
    main.positions.clear()
    source = _empty_position(0, 0)
    source.set_piece(3, 3, Piece(PieceType.ROOK, ChessColor.WHITE))
    main.add_position(source)
    other = Timeline(timeline_id=1, owner=ChessColor.WHITE)
    other.add_position(_empty_position(1, 0))
    manager.timelines[1] = other
    manager.refresh_activity()
    _reset_white_action(engine)
    return engine


def test_easy_plan_is_complete_and_submit_capable_without_mutating_engine():
    engine = FiveDEngine()
    before = engine_state_signature(engine)
    plan = RandomAI(ChessColor.WHITE, seed=7, budget=FAST_BUDGET).plan_action(engine)

    assert plan.moves
    assert engine_state_signature(engine) == before
    clone = deepcopy(engine)
    applied = apply_action_plan(clone, plan)
    assert len(applied) == len(plan.moves)
    assert clone.current_turn_color == ChessColor.BLACK
    assert len(clone.action_history) == 1
    assert clone.action_history[0].submitted


def test_standard_position_white_and_black_ai_complete_actions():
    engine = FiveDEngine()
    white = RandomAI(ChessColor.WHITE, seed=1, budget=FAST_BUDGET).plan_action(engine)
    apply_action_plan(engine, white)
    black = RandomAI(ChessColor.BLACK, seed=1, budget=FAST_BUDGET).plan_action(engine)
    apply_action_plan(engine, black)

    assert engine.current_turn_color == ChessColor.WHITE
    assert len(engine.action_history) == 2
    assert all(action.submitted for action in engine.action_history)


def test_two_required_boards_prioritize_direct_cross_timeline_completion():
    engine = _two_required_boards_engine()
    before = engine_state_signature(engine)
    required = set(ActionRules.required_boards(
        engine._ensure_current_action(),
        engine.timeline_manager.timelines,
    ))
    assert len(required) == 2

    result = ActionPlanner(ActionSearchBudget(
        max_states=1,
        max_actions=1,
        max_move_depth=1,
        max_seconds=None,
    )).search(engine)

    assert engine_state_signature(engine) == before
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert len(candidate) == 1
    spec = candidate[0]
    assert spec.source.board in required
    assert spec.destination.board in required
    assert spec.source.board != spec.destination.board

    plan = AIActionPlan(
        color=ChessColor.WHITE,
        moves=candidate,
        start_signature=before,
    )
    applied = apply_action_plan(engine, plan)
    assert len(applied) == 1
    assert len(engine.action_history) == 1
    assert engine.action_history[0].submitted
    assert engine.current_turn_color == ChessColor.BLACK


def test_branching_candidates_are_not_filtered_out():
    engine = _branching_engine()
    legal_branch_specs = {
        (move.source, move.destination)
        for move in engine.get_legal_moves()
        if move.is_branching
    }
    assert legal_branch_specs

    result = ActionPlanner(ActionSearchBudget(512, 256, 8, 2.0)).search(engine)
    assert any(
        candidate and (candidate[0].source, candidate[0].destination) in legal_branch_specs
        for candidate in result.candidates
    )


def test_cross_timeline_candidates_are_not_filtered_out():
    engine = _cross_timeline_engine()
    legal_cross_specs = {
        (move.source, move.destination)
        for move in engine.get_legal_moves()
        if move.is_cross_timeline
    }
    assert legal_cross_specs

    result = ActionPlanner(ActionSearchBudget(1024, 512, 8, 3.0)).search(engine)
    assert any(
        any((spec.source, spec.destination) in legal_cross_specs for spec in candidate)
        for candidate in result.candidates
    )


def test_medium_evaluates_only_after_a_submitted_action(monkeypatch):
    engine = FiveDEngine()
    ai = AlphaBetaAI(ChessColor.WHITE, search_depth=1, budget=FAST_BUDGET)
    observed = []

    def evaluate(candidate, perspective):
        observed.append((candidate.current_turn_color, len(candidate.action_history)))
        return 0.0

    monkeypatch.setattr(ai.evaluator, "evaluate_engine", evaluate)
    ai.plan_action(engine)
    assert observed
    assert all(turn == ChessColor.BLACK and actions == 1 for turn, actions in observed)


def test_hard_depth_is_measured_at_action_boundaries(monkeypatch):
    engine = FiveDEngine()
    budget = ActionSearchBudget(512, 2, 8, 2.0)
    ai = HardAI(ChessColor.WHITE, search_depth=2, budget=budget)
    observed = []

    def evaluate(candidate, perspective):
        observed.append((candidate.current_turn_color, len(candidate.action_history)))
        return 0.0

    monkeypatch.setattr(ai.evaluator, "evaluate_engine", evaluate)
    ai.plan_action(engine)
    assert any(turn == ChessColor.WHITE and actions == 2 for turn, actions in observed)


def test_fixed_seed_is_reproducible():
    first = RandomAI(ChessColor.WHITE, seed=2026, budget=FAST_BUDGET).plan_action(
        FiveDEngine()
    )
    second = RandomAI(ChessColor.WHITE, seed=2026, budget=FAST_BUDGET).plan_action(
        FiveDEngine()
    )
    assert first.moves == second.moves


def test_wrong_turn_ai_cannot_plan_opponent_action():
    with pytest.raises(ActionPlanningError) as exc_info:
        RandomAI(ChessColor.BLACK, seed=1, budget=FAST_BUDGET).plan_action(
            FiveDEngine()
        )
    assert exc_info.value.reason == "wrong_turn"


def test_plan_application_cannot_move_an_opponent_piece():
    engine = FiveDEngine()
    forged = AIActionPlan(
        color=ChessColor.WHITE,
        moves=(MoveSpec(
            Square5D(BoardCoord(0, 0, ChessColor.WHITE), 4, 1),
            Square5D(BoardCoord(0, 0, ChessColor.WHITE), 4, 2),
        ),),
        start_signature=engine_state_signature(engine),
    )
    with pytest.raises(ActionApplicationError):
        apply_action_plan(engine, forged)
    assert engine.move_history == []
    assert engine.current_turn_color == ChessColor.WHITE


def test_stale_plan_is_rejected_before_application():
    engine = FiveDEngine()
    plan = RandomAI(ChessColor.WHITE, seed=4, budget=FAST_BUDGET).plan_action(engine)
    legal = engine.get_legal_moves()[0]
    assert engine.execute_action_move(legal)

    with pytest.raises(StaleActionPlanError):
        apply_action_plan(engine, plan)
    assert engine.action_history == []


def test_budget_exhaustion_is_explicit_and_not_terminal():
    engine = FiveDEngine()
    started = time.monotonic()
    with pytest.raises(ActionPlanningError) as exc_info:
        RandomAI(
            ChessColor.WHITE,
            seed=1,
            budget=ActionSearchBudget(0, 8, 8, 1.0),
        ).plan_action(engine)
    assert time.monotonic() - started < 0.5
    assert exc_info.value.incomplete
    assert exc_info.value.reason == "state_budget"
    assert engine.game_state.name == "PLAYING"


def test_planner_time_budget_uses_monotonic_clock(monkeypatch):
    ticks = iter((100.0, 102.0))
    monkeypatch.setattr(
        "src.ai.action_planner.time.monotonic",
        lambda: next(ticks),
    )
    result = ActionPlanner(ActionSearchBudget(128, 8, 8, 1.0)).search(
        FiveDEngine()
    )
    assert result.candidates == ()
    assert result.termination_reason == "time_budget"


def test_completed_candidate_survives_bounded_search_warning():
    engine = FiveDEngine()
    plan = RandomAI(
        ChessColor.WHITE,
        seed=1,
        budget=ActionSearchBudget(64, 1, 8, 1.0),
    ).plan_action(engine)
    assert plan.moves
    assert plan.warning and "action_budget" in plan.warning


def test_action_move_depth_guard_returns_without_looping():
    engine = _two_required_boards_engine()
    started = time.monotonic()
    with pytest.raises(ActionPlanningError) as exc_info:
        RandomAI(
            ChessColor.WHITE,
            seed=1,
            budget=ActionSearchBudget(128, 8, 0, 1.0),
        ).plan_action(engine)
    assert time.monotonic() - started < 0.5
    assert exc_info.value.incomplete
    assert exc_info.value.reason == "move_depth_budget"


def test_pve_mode_rejects_ai_on_player_turn():
    mode = PvEMode(player_color=ChessColor.WHITE, ai_difficulty="easy")
    result = mode.execute_ai_action()
    assert not result["success"]
    assert result["error_code"] == "wrong_turn"
    assert mode.engine.move_history == []


def test_pve_mode_rejects_stale_snapshot_plan(monkeypatch):
    mode = PvEMode(player_color=ChessColor.BLACK, ai_difficulty="easy")
    original = mode.ai.plan_action

    def mutate_live_then_plan(snapshot):
        mode.engine.move_counter += 1
        return original(snapshot)

    monkeypatch.setattr(mode.ai, "plan_action", mutate_live_then_plan)
    result = mode.execute_ai_action()
    assert not result["success"]
    assert result["error_code"] == "stale_plan"
    assert mode.engine.action_history == []


def test_pve_mode_rejects_a_second_concurrent_ai_planner(monkeypatch):
    mode = PvEMode(player_color=ChessColor.BLACK, ai_difficulty="easy")
    entered = threading.Event()
    release = threading.Event()
    original = mode.ai.plan_action

    def blocked_plan(snapshot):
        entered.set()
        assert release.wait(1.0)
        return original(snapshot)

    monkeypatch.setattr(mode.ai, "plan_action", blocked_plan)
    first_result = {}
    worker = threading.Thread(
        target=lambda: first_result.update(mode.execute_ai_action()),
        daemon=True,
    )
    worker.start()
    assert entered.wait(1.0)
    second = mode.execute_ai_action()
    assert not second["success"]
    assert second["error_code"] == "busy"
    release.set()
    worker.join(2.0)
    assert not worker.is_alive()
    assert first_result["success"]
    assert len(mode.engine.action_history) == 1


@pytest.fixture()
def client():
    app.config.update(TESTING=True)
    _game_session.update({
        "mode": None,
        "mode_instance": None,
        "ai_difficulty": "medium",
        "player_color": None,
    })
    with app.test_client() as test_client:
        yield test_client
    _game_session.update({
        "mode": None,
        "mode_instance": None,
        "ai_difficulty": "medium",
        "player_color": None,
    })


def _start_and_submit_white_action(client, difficulty: str):
    state = client.post(
        "/api/game/start",
        json={"mode": "pve", "difficulty": difficulty, "player_color": "white"},
    ).get_json()
    board = state["boards"][0]
    moves = client.post(
        "/api/game/legal_moves_5d",
        json={"board": board["coord"], "x": 4, "y": 6},
    ).get_json()["moves"]
    move = next(item for item in moves if item["destination"]["y"] == 4)
    moved = client.post(
        "/api/game/move_5d",
        json={"source": move["source"], "destination": move["destination"]},
    ).get_json()
    assert moved["turn"] == "white"
    submitted = client.post("/api/game/submit_action", json={}).get_json()
    assert submitted["turn"] == "black"


@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_pve_web_difficulties_complete_one_canonical_ai_action(client, difficulty):
    _start_and_submit_white_action(client, difficulty)
    response = client.post("/api/game/ai_move", json={})
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"]
    assert data["moves"]
    assert data["turn"] == "white"
    assert data["action"]["move_count"] == 0


def test_white_ai_can_open_when_player_chooses_black(client):
    started = client.post(
        "/api/game/start",
        json={"mode": "pve", "difficulty": "easy", "player_color": "black"},
    ).get_json()
    assert started["turn"] == "white"
    response = client.post("/api/game/ai_move", json={})
    assert response.status_code == 200
    assert response.get_json()["turn"] == "black"
