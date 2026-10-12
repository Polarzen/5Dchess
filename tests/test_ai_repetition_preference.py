"""AI preferences use canonical frontier evidence without banning repetitions."""
from dataclasses import replace

import pytest

from src.ai.action_planner import (
    ActionPlanner, ActionSearchBudget, MoveSpec, engine_state_signature,
    resolve_move_spec,
)
from src.ai.alpha_beta import AlphaBetaAI
from src.ai.hard_ai import HardAI
from src.ai.random_ai import RandomAI
from src.engine import ActionRules, FiveDEngine, Position, Timeline
from src.engine.repetition import detect_frontier_repetition, repeated_frontier_counts
from src.utils.constants import ChessColor, GameState


CYCLE = [((6, 7), (5, 5)), ((6, 0), (5, 2)),
         ((5, 5), (6, 7)), ((5, 2), (6, 0))]
BUDGET = ActionSearchBudget(2048, 64, 2, None)


def before_third_occurrence(lanes=1):
    engine = FiveDEngine(max_timelines=lanes)
    if lanes == 2:
        engine.timeline_manager.timelines[1] = Timeline(1, positions={0: Position.initial(1)})
        engine.current_action = ActionRules.begin(ChessColor.WHITE, engine.timeline_manager.timelines)
    for index in range(7):
        source, destination = CYCLE[index % 4]
        for lane in engine.timeline_manager.timelines.values():
            pos = lane.positions[lane.latest_time]
            move = next(m for m in engine.get_legal_moves_from_square(pos, *source)
                        if m.is_spatial and (m.to_x, m.to_y) == destination)
            assert engine.execute_action_move(move)
        assert engine.submit_action(evaluate_outcome=False)
    return engine


def replay(engine, specs):
    child = engine.clone_for_simulation()
    for spec in specs:
        assert child.execute_action_move(resolve_move_spec(child, spec))
    assert child.submit_action(evaluate_outcome=False)
    return child


@pytest.mark.parametrize('strategy', ['depth_first', 'probe_then_depth_first'])
@pytest.mark.parametrize('lanes', [1, 2])
def test_annotations_match_canonical_submissions_without_changing_candidates(strategy, lanes):
    engine = before_third_occurrence(lanes)
    before = engine_state_signature(engine)
    plain = ActionPlanner(BUDGET, strategy=strategy).search(engine)
    tracked = ActionPlanner(BUDGET, strategy=strategy, track_repetition=True).search(engine)
    assert tracked.candidates == plain.candidates
    assert tracked.explored_states == plain.explored_states
    assert len(tracked.frontier_repetitions) == len(tracked.candidates)
    assert any(count >= 2 for count in tracked.frontier_repetitions)
    assert 0 in tracked.frontier_repetitions
    for specs, count in zip(tracked.candidates, tracked.frontier_repetitions):
        child = replay(engine, specs)
        warning = detect_frontier_repetition(child)
        assert (count >= 2) == (warning is not None)
        if warning:
            assert warning.occurrences == count + 1
        assert child.game_state == GameState.PLAYING
    assert engine_state_signature(engine) == before


@pytest.fixture
def choices():
    engine = before_third_occurrence()
    result = ActionPlanner(BUDGET, track_repetition=True).search(engine)
    repeated = next(i for i, count in enumerate(result.frontier_repetitions) if count >= 2)
    fresh = next(i for i, count in enumerate(result.frontier_repetitions) if count == 0)
    # Put the repeat first: old deterministic/first-choice behavior repeats.
    result = replace(result, candidates=(result.candidates[repeated], result.candidates[fresh]),
                     frontier_repetitions=(2, 0))
    return engine, result


class FirstChoice:
    def choice(self, values):
        return values[0]


def install_result(monkeypatch, module, result):
    class Planner:
        def __init__(self, budget, *, track_repetition):
            assert track_repetition

        def search(self, engine):
            return result

    monkeypatch.setattr(module, 'ActionPlanner', Planner)


@pytest.mark.parametrize('only_repeat', [False, True])
def test_easy_prefers_progress_but_keeps_only_legal_repeat(monkeypatch, choices, only_repeat):
    import src.ai.random_ai as module
    engine, result = choices
    if only_repeat:
        result = replace(result, candidates=result.candidates[:1], frontier_repetitions=(2,))
    install_result(monkeypatch, module, result)
    before = engine_state_signature(engine)
    plan = RandomAI(engine.current_turn_color, rng=FirstChoice()).plan_action(engine)
    assert plan.moves == result.candidates[0 if only_repeat else 1]
    assert bool(detect_frontier_repetition(replay(engine, plan.moves))) == only_repeat
    assert engine_state_signature(engine) == before


@pytest.mark.parametrize('ai_type', [AlphaBetaAI, HardAI])
@pytest.mark.parametrize('repeat_advantage,expect_repeat', [(0.0, False), (0.1, False), (1.0, True)])
def test_minimax_near_ties_prefer_progress_but_keep_superior_repeat(
        monkeypatch, choices, ai_type, repeat_advantage, expect_repeat):
    engine, result = choices
    ai = ai_type(engine.current_turn_color, search_depth=1, budget=BUDGET)
    monkeypatch.setattr(ai, '_search_candidates', lambda *args, **kwargs: result)
    observed_bounds = []

    def score(child, depth, alpha, beta):
        observed_bounds.append(alpha)
        move = MoveSpec.from_move(child.action_history[-1].moves[0])
        return repeat_advantage if move == result.candidates[0][0] else 0.0

    monkeypatch.setattr(ai, '_search_state', score)
    before = engine_state_signature(engine)
    plan = ai.plan_action(engine)
    assert plan.moves == result.candidates[0 if expect_repeat else 1]
    assert plan.score == pytest.approx(repeat_advantage if expect_repeat else 0.0)
    # The raw subtree must receive alpha adjusted by the root-only cost.
    assert observed_bounds == [float('-inf'), 0.25]
    assert engine_state_signature(engine) == before


def test_minimax_retains_repeat_when_it_is_the_only_candidate(monkeypatch, choices):
    engine, result = choices
    result = replace(result, candidates=result.candidates[:1], frontier_repetitions=(2,))
    ai = HardAI(engine.current_turn_color, search_depth=1, budget=BUDGET)
    monkeypatch.setattr(ai, '_search_candidates', lambda *args, **kwargs: result)
    monkeypatch.setattr(ai, '_search_state', lambda *args: 0.0)
    plan = ai.plan_action(engine)
    assert plan.moves == result.candidates[0]
    assert detect_frontier_repetition(replay(engine, plan.moves))


def test_minimax_deadline_fallback_keeps_a_valid_progress_candidate(monkeypatch, choices):
    engine, result = choices
    ai = HardAI(engine.current_turn_color, budget=BUDGET)
    monkeypatch.setattr(ai, '_search_candidates', lambda *args, **kwargs: result)
    monkeypatch.setattr(ai, '_deadline_reached', lambda: True)
    monkeypatch.setattr(ai.evaluator, 'evaluate_engine', lambda *args: 0.0)
    plan = ai.plan_action(engine)
    assert plan.moves == result.candidates[1]
    assert 'time_budget' in plan.warning
    replay(engine, plan.moves)


@pytest.mark.parametrize('repeat_advantage,expect_repeat,only_repeat',
                         [(0.0, False, False), (0.05, False, False),
                          (1.0, True, False), (0.0, True, True)])
def test_neural_near_ties_prefer_progress_preserving_raw_logits(
        monkeypatch, choices, repeat_advantage, expect_repeat, only_repeat):
    torch = pytest.importorskip('torch')
    import src.training.agent as module
    from src.training.config import DEFAULT_ENCODING
    engine, result = choices
    if only_repeat:
        result = replace(result, candidates=result.candidates[:1], frontier_repetitions=(2,))
    install_result(monkeypatch, module, result)

    class Model(torch.nn.Module):
        encoding_config = DEFAULT_ENCODING

        def forward(self, *args):
            return torch.tensor([[repeat_advantage, 0.0][:len(result.candidates)]]), torch.tensor([0.0])

    ai = module.NeuralPolicyValueAgent(Model(), engine.current_turn_color)
    before = engine_state_signature(engine)
    plan = ai.plan_action(engine)
    assert plan.moves == result.candidates[0 if expect_repeat else 1]
    assert ai.last_decision.logits == pytest.approx((repeat_advantage, 0.0)[:len(result.candidates)])
    assert plan.score == pytest.approx(repeat_advantage if expect_repeat else 0.0)
    replay(engine, plan.moves)
    assert engine_state_signature(engine) == before


def test_history_scan_is_bounded_interruptible_and_ignores_partial_actions():
    engine = before_third_occurrence()
    assert repeated_frontier_counts(engine)
    assert repeated_frontier_counts(engine, max_actions=2) == {}
    assert repeated_frontier_counts(engine, should_stop=lambda: True) == {}
    move = engine.get_legal_moves()[0]
    assert engine.execute_action_move(move)
    assert repeated_frontier_counts(engine) == {}


def test_tracking_obeys_existing_zero_wall_budget():
    result = ActionPlanner(ActionSearchBudget(max_seconds=0), track_repetition=True).search(
        before_third_occurrence())
    assert result.candidates == () and result.frontier_repetitions == ()
    assert result.termination_reason == 'time_budget'


def test_new_branch_is_not_mistaken_for_a_frontier_repeat():
    engine = before_third_occurrence()
    engine.max_timelines = engine.timeline_manager.max_timelines = 2
    budget = ActionSearchBudget(2048, 128, 1, None)
    result = ActionPlanner(budget, strategy='probe_then_depth_first', track_repetition=True).search(engine)
    branches = [(specs, count) for specs, count in zip(result.candidates, result.frontier_repetitions)
                if resolve_move_spec(engine, specs[0]).is_branching]
    assert branches
    for specs, count in branches:
        child = replay(engine, specs)
        assert count == 0
        assert detect_frontier_repetition(child) is None
        assert repeated_frontier_counts(child) == {}


def test_history_preparation_is_charged_to_planning_deadline(monkeypatch):
    import src.ai.action_planner as module
    engine = before_third_occurrence()
    now = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])

    def delayed_history(state, *, max_actions, should_stop):
        assert max_actions == 63
        now[0] = 106.0
        assert should_stop()
        return {}

    monkeypatch.setattr(module, 'repeated_frontier_counts', delayed_history)
    result = ActionPlanner(ActionSearchBudget(max_seconds=5.0), track_repetition=True).search(engine)
    assert result.candidates == () and result.termination_reason == 'time_budget'
