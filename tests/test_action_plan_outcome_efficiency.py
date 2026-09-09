"""Regression tests for one-pass Action-plan outcome evaluation."""
from copy import deepcopy

import pytest

from src.ai import (
    AIActionPlan,
    ActionSearchBudget,
    MoveSpec,
    RandomAI,
    apply_action_plan,
    engine_state_signature,
)
from src.engine import ActionRules, FiveDEngine, Position, Timeline, TimelineManager
from src.utils.constants import ChessColor, GameState


def _plan(engine: FiveDEngine) -> AIActionPlan:
    return RandomAI(
        engine.current_turn_color,
        seed=17,
        budget=ActionSearchBudget(
            max_states=256,
            max_actions=8,
            max_move_depth=8,
            max_seconds=1.0,
        ),
    ).plan_action(engine)


def _make_position(
    timeline_id: int,
    time_point: int,
    pieces: dict[tuple[int, int], str],
) -> Position:
    board = [["" for _ in range(8)] for _ in range(8)]
    for (x, y), piece in pieces.items():
        board[y][x] = piece
    return Position(
        board=board,
        turn=ChessColor.WHITE if time_point % 2 == 0 else ChessColor.BLACK,
        timeline_id=timeline_id,
        time_point=time_point,
        castling_rights={
            "white_kingside": False,
            "white_queenside": False,
            "black_kingside": False,
            "black_queenside": False,
        },
    )


def _install_position(engine: FiveDEngine, position: Position, color: ChessColor) -> None:
    timeline = Timeline(timeline_id=0)
    timeline.add_position(position)
    manager = TimelineManager(max_timelines=engine.max_timelines)
    manager.timelines = {0: timeline}
    manager.active_timeline_id = 0
    manager.refresh_activity()
    engine.timeline_manager = manager
    engine.game_state = GameState.PLAYING
    engine.move_history = []
    engine.action_history = []
    engine.move_counter = 0
    engine.current_turn_color = color
    engine.current_action = ActionRules.begin(color, manager.timelines)


def _specific_plan(engine: FiveDEngine, coords: tuple[int, int, int, int]) -> AIActionPlan:
    position = engine.get_current_position()
    move = next(
        move
        for move in engine.get_legal_moves(position)
        if (
            move.source.x,
            move.source.y,
            move.destination.x,
            move.destination.y,
        ) == coords
    )
    return AIActionPlan(
        color=engine.current_turn_color,
        moves=(MoveSpec.from_move(move),),
        start_signature=engine_state_signature(engine),
    )


def test_apply_action_plan_evaluates_outcome_once_before_live_mutation(monkeypatch):
    engine = FiveDEngine()
    plan = _plan(engine)
    evaluated_on = []
    checked_on = []
    original_evaluate = FiveDEngine._evaluate_multiverse_game_result
    original_check = FiveDEngine._check_multiverse_game_result

    def tracked_evaluate(self):
        evaluated_on.append(self)
        return original_evaluate(self)

    def tracked_check(self, *args, **kwargs):
        checked_on.append((self, kwargs))
        return original_check(self, *args, **kwargs)

    monkeypatch.setattr(FiveDEngine, "_evaluate_multiverse_game_result", tracked_evaluate)
    monkeypatch.setattr(FiveDEngine, "_check_multiverse_game_result", tracked_check)

    assert apply_action_plan(engine, plan)

    assert len(evaluated_on) == 1
    assert evaluated_on[0] is not engine
    assert len(checked_on) == 1
    assert checked_on[0][0] is engine
    assert "precomputed_outcome" in checked_on[0][1]


def test_default_submit_action_still_evaluates_outcome_on_live_engine(monkeypatch):
    engine = FiveDEngine()
    position = engine.get_current_position()
    move = engine.get_legal_moves(position)[0]
    assert engine.execute_action_move(move)

    evaluated_on = []
    original_evaluate = FiveDEngine._evaluate_multiverse_game_result

    def tracked_evaluate(self):
        evaluated_on.append(self)
        return original_evaluate(self)

    monkeypatch.setattr(FiveDEngine, "_evaluate_multiverse_game_result", tracked_evaluate)

    assert engine.submit_action()
    assert evaluated_on == [engine]


@pytest.mark.parametrize(
    "pieces, move_coords, expected_state",
    [
        (
            {(7, 7): "K", (6, 5): "q", (5, 5): "k"},
            (6, 5, 6, 6),
            GameState.CHECKMATE,
        ),
        (
            {(7, 7): "K", (5, 4): "q", (5, 6): "k"},
            (5, 4, 6, 5),
            GameState.STALEMATE,
        ),
    ],
)
def test_apply_action_plan_preserves_terminal_semantics(
    pieces, move_coords, expected_state
):
    engine = FiveDEngine()
    _install_position(engine, _make_position(0, 1, pieces), ChessColor.BLACK)
    baseline = deepcopy(engine)
    plan = _specific_plan(engine, move_coords)

    baseline_move = next(
        move
        for move in baseline.get_legal_moves(baseline.get_current_position())
        if (
            move.source.x,
            move.source.y,
            move.destination.x,
            move.destination.y,
        ) == move_coords
    )
    assert baseline.execute_move(baseline_move)

    assert apply_action_plan(engine, plan)
    assert engine.game_state == expected_state
    assert engine_state_signature(engine) == engine_state_signature(baseline)


def test_apply_action_plan_preserves_nonterminal_state_semantics():
    engine = FiveDEngine()
    baseline = deepcopy(engine)
    plan = _plan(engine)

    baseline_moves = []
    for spec in plan.moves:
        position = baseline._resolve_position(spec.source.board)
        move = next(
            move
            for move in baseline.get_legal_moves_from_square(
                position, spec.source.x, spec.source.y
            )
            if (
                move.source == spec.source
                and move.destination == spec.destination
                and move.promotion == spec.promotion
            )
        )
        assert baseline.execute_action_move(move)
        baseline_moves.append(move)
    assert baseline.submit_action()

    assert apply_action_plan(engine, plan)
    assert engine.game_state == GameState.PLAYING
    assert engine_state_signature(engine) == engine_state_signature(baseline)
