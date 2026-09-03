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
    # Occupy the same square on both required boards so a rook cannot satisfy
    # both with one direct cross-timeline Move. This fixture intentionally
    # requires two Moves and therefore remains a valid move-depth guard test
    # even when the planner prioritizes legal two-board progress elsewhere.
    second.set_piece(0, 6, rook)
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


def test_multiple_required_boards_produce_multi_move_single_submit_action():
    engine = _two_required_boards_engine()
    plan = RandomAI(ChessColor.WHITE, seed=2, budget=FAST_BUDGET).plan_action(engine)
    applied = apply_action_plan(engine, plan)

    assert len(applied) >= 2
    assert len(engine.action_history) == 1
    assert len(engine.action_history[0].moves) == len(applied)
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

    result = ActionPlanner(ActionSearchBudget(512, 256, 8, 2.0)).search(engine)
    assert any(
        any((spec.source, spec.destination) in legal_cross_specs for spec in candidate)
        for candidate in result.candidates
    )


def test_promotion_spec_round_trip_uses_canonical_piece_type():
    source = Square5D(BoardCoord(0, 1, ChessColor.WHITE), 0, 1)
    destination = Square5D(BoardCoord(0, 1, ChessColor.WHITE), 0, 0)
    spec = MoveSpec(source, destination, PieceType.QUEEN)
    assert spec.promotion is PieceType.QUEEN


def test_stale_plan_is_rejected_without_mutating_engine():
    engine = FiveDEngine()
    plan = RandomAI(ChessColor.WHITE, seed=3, budget=FAST_BUDGET).plan_action(engine)
    _advance_one_action(engine)
    before = engine_state_signature(engine)

    with pytest.raises(StaleActionPlanError):
        apply_action_plan(engine, plan)

    assert engine_state_signature(engine) == before


def test_invalid_plan_is_rejected_atomically():
    engine = FiveDEngine()
    before = engine_state_signature(engine)
    source = Square5D(BoardCoord(0, 0, ChessColor.WHITE), 0, 0)
    destination = Square5D(BoardCoord(0, 0, ChessColor.WHITE), 0, 1)
    plan = AIActionPlan(
        color=ChessColor.WHITE,
        moves=(MoveSpec(source, destination),),
        start_signature=before,
    )

    with pytest.raises(ActionApplicationError):
        apply_action_plan(engine, plan)
    assert engine_state_signature(engine) == before


def test_plan_metadata_is_immutable():
    engine = FiveDEngine()
    plan = RandomAI(ChessColor.WHITE, seed=4, budget=FAST_BUDGET).plan_action(engine)
    with pytest.raises(TypeError):
        plan.metadata["mutated"] = True


def test_alpha_beta_plan_is_complete_and_uses_canonical_application():
    engine = FiveDEngine()
    before = engine_state_signature(engine)
    ai = AlphaBetaAI(
        ChessColor.WHITE,
        max_depth=1,
        time_limit=1.0,
        action_budget=FAST_BUDGET,
    )
    plan = ai.plan_action(engine)
    assert engine_state_signature(engine) == before
    apply_action_plan(engine, plan)
    assert engine.current_turn_color == ChessColor.BLACK


def test_hard_ai_plan_is_complete_and_uses_canonical_application():
    engine = FiveDEngine()
    before = engine_state_signature(engine)
    ai = HardAI(
        ChessColor.WHITE,
        max_depth=1,
        time_limit=1.0,
        action_budget=FAST_BUDGET,
    )
    plan = ai.plan_action(engine)
    assert engine_state_signature(engine) == before
    apply_action_plan(engine, plan)
    assert engine.current_turn_color == ChessColor.BLACK


def test_planner_state_budget_returns_without_looping():
    engine = _two_required_boards_engine()
    started = time.monotonic()
    with pytest.raises(ActionPlanningError) as exc_info:
        RandomAI(
            ChessColor.WHITE,
            seed=1,
            budget=ActionSearchBudget(1, 8, 8, 1.0),
        ).plan_action(engine)
    assert time.monotonic() - started < 0.5
    assert exc_info.value.incomplete
    assert exc_info.value.reason == "state_budget"


def test_planner_action_budget_stops_after_complete_candidate():
    engine = FiveDEngine()
    result = ActionPlanner(ActionSearchBudget(128, 1, 8, 1.0)).search(engine)
    assert len(result.candidates) == 1
    assert result.termination_reason == "action_budget"


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
            budget=ActionSearchBudget(128, 8, 1, 1.0),
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
    started = threading.Event()
    release = threading.Event()

    def delayed(snapshot):
        started.set()
        release.wait(timeout=2.0)
        return original(snapshot)

    monkeypatch.setattr(mode.ai, "plan_action", delayed)
    result_box = {}

    def worker():
        result_box["result"] = mode.execute_ai_action()

    thread = threading.Thread(target=worker)
    thread.start()
    assert started.wait(timeout=1.0)
    _advance_one_action(mode.engine)
    release.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive()

    result = result_box["result"]
    assert not result["success"]
    assert result["error_code"] == "stale_action"


def test_pve_mode_applies_ai_action_atomically(monkeypatch):
    mode = PvEMode(player_color=ChessColor.BLACK, ai_difficulty="easy")
    original = mode.ai.plan_action

    def plan_from_snapshot(snapshot):
        return original(snapshot)

    monkeypatch.setattr(mode.ai, "plan_action", plan_from_snapshot)
    result = mode.execute_ai_action()
    assert result["success"]
    assert mode.engine.current_turn_color == ChessColor.BLACK
