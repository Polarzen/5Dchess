"""Minimax candidate ordering must not depend on clock resolution."""
import gzip
import json
from pathlib import Path

import pytest

import src.ai.action_planner as planning
import src.ai.alpha_beta as minimax
from src.ai.action_planner import (
    ActionPlanner, ActionSearchBudget, ActionSearchResult,
    _PRODUCTION_HYBRID_BUDGET, apply_action_plan, engine_state_signature,
)
from src.ai.hard_ai import HardAI
from src.data.archive import GameArchive
from src.engine import ActionRules, BoardCoord, FiveDEngine, Position, Timeline
from src.utils.constants import ChessColor


def _captured(name):
    path = Path(__file__).parent / 'fixtures' / f'{name}.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(path.read_bytes())))
    del engine._replay_origin
    return engine


def _safe_frontier(count=6):
    """Known legal multi-board state; old traces included unsafe royal arrivals."""
    engine = FiveDEngine()
    manager = engine.timeline_manager
    manager.timelines = {}
    for lane in list(range(-2, 4))[:count]:
        board = [[''] * 8 for _ in range(8)]
        board[7][7], board[0][7], board[6][4] = 'K', 'k', 'P'
        if lane == 0:
            board[4][3] = 'R'
        pos = Position(board, ChessColor.WHITE, lane, 0)
        manager.timelines[lane] = Timeline(lane, positions={0: pos})
    manager._next_positive_id = max(manager.timelines) + 1
    manager._next_negative_id = min(manager.timelines) - 1
    engine.current_action = ActionRules.begin(ChessColor.WHITE, manager.timelines)
    assert len(engine.get_required_action_boards()) == count
    return engine


@pytest.mark.parametrize('elapsed', [0.0, 0.001])
def test_minimax_keeps_strategy_and_shares_deadline_and_states(monkeypatch, elapsed):
    now = [100.0 + elapsed]
    monkeypatch.setattr(minimax.time, 'monotonic', lambda: now[0])
    calls = []

    class RecordingPlanner:
        def __init__(self, budget, *, strategy, deadline):
            calls.append((budget, strategy, deadline))

        def search(self, engine):
            return ActionSearchResult((), 7, 'move_depth_budget')

    monkeypatch.setattr(minimax, 'ActionPlanner', RecordingPlanner)
    ai = HardAI(ChessColor.WHITE, budget=_PRODUCTION_HYBRID_BUDGET)
    ai._start_time = 100.0
    ai._search_candidates(None)
    now[0] = 102.0
    ai._search_candidates(None)
    assert [call[1:] for call in calls] == [('probe_then_depth_first', 105.0)] * 2
    assert calls[0][0].max_seconds == pytest.approx(5.0 - elapsed)
    assert (calls[0][0].max_states, calls[0][0].max_actions,
            calls[0][0].max_move_depth) == (1024, 24, 32)
    assert calls[1][0] == ActionSearchBudget(1017, 24, 32, 3.0)
    assert ai._states_used == 14
    now[0] = 105.0
    result = ai._search_candidates(None)
    assert result.termination_reason == 'time_budget'
    assert len(calls) == 2


@pytest.mark.parametrize('seconds', [5.0, 4.999])
def test_explicit_depth_first_has_same_candidates_at_clock_boundary(monkeypatch, seconds):
    engine = _safe_frontier()
    before = engine_state_signature(engine)
    monkeypatch.setattr(planning.time, 'monotonic', lambda: 100.0)
    legacy = ActionPlanner(ActionSearchBudget(1024, 24, 32, 4.999)).search(engine)
    planner = ActionPlanner(ActionSearchBudget(1024, 24, 32, seconds),
                            strategy='depth_first', deadline=105.0)
    result = planner.search(engine)
    assert legacy.candidates and result.candidates == legacy.candidates
    assert result.explored_states == legacy.explored_states
    assert planner.search_telemetry == ()
    assert engine_state_signature(engine) == before


@pytest.mark.parametrize('seconds', [None, 5.0])
@pytest.mark.parametrize('strategy', ['depth_first', 'probe_then_depth_first'])
def test_absolute_deadline_includes_clone_preparation(monkeypatch, seconds, strategy):
    engine = FiveDEngine()
    before = engine_state_signature(engine)
    now = [100.0]
    monkeypatch.setattr(planning.time, 'monotonic', lambda: now[0])
    original = FiveDEngine.clone_for_simulation

    def delayed_clone(self):
        child = original(self)
        now[0] = 101.1
        return child

    monkeypatch.setattr(FiveDEngine, 'clone_for_simulation', delayed_clone)
    result = ActionPlanner(ActionSearchBudget(1024, 24, 32, seconds), strategy=strategy,
                           deadline=101.0).search(engine)
    assert result.candidates == ()
    assert result.termination_reason == 'time_budget'
    assert result.explored_states == 0
    assert engine_state_signature(engine) == before


@pytest.mark.parametrize('fixture', [
    'fresh_four_required', 'fresh_six_required',
    'hard20_rewind_four_state', 'hard20_rewind_three_state',
    'hard20_eight_required_rewind_state',
    'hard_replay_169_state',
])
def test_hard_captured_root_returns_canonical_action_with_primary_budget(fixture):
    engine = (_safe_frontier(4 if fixture == 'fresh_four_required' else 6)
              if fixture.startswith('fresh_') else _captured(fixture))
    before = engine_state_signature(engine)
    ai = HardAI(engine.current_turn_color, search_depth=2, budget=_PRODUCTION_HYBRID_BUDGET)
    plan = ai.plan_action(engine)
    assert 0 < plan.metadata['candidate_count'] <= 24
    assert plan.metadata['explored_states'] <= 1024
    assert 0 < len(plan.moves) <= 32
    child = engine.clone_for_simulation()
    apply_action_plan(child, plan)
    assert child.action_history[-1].submitted
    assert engine_state_signature(engine) == before


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError, match='strategy'):
        ActionPlanner(strategy='unknown')


@pytest.mark.parametrize('fixture', ['hard_replay_169_state', 'hard_replay_200_state'])
def test_web_hard_completes_saved_frontier_without_extra_budget(fixture):
    path = Path(__file__).parent / 'fixtures' / f'{fixture}.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(path.read_bytes())))
    before = engine_state_signature(engine)
    assert len(engine.get_required_action_boards()) >= 16
    ai = HardAI(engine.current_turn_color)
    assert ai.budget == ActionSearchBudget(1536, 12, 32, 2.0)
    plan = ai.plan_action(engine)
    assert 0 < plan.metadata['candidate_count'] <= 12
    assert plan.metadata['explored_states'] <= 1536
    assert 0 < len(plan.moves) <= 32
    child = planning._clone_state_for_action_search(engine)
    apply_action_plan(child, plan)
    assert child.action_history[-1].submitted
    assert engine_state_signature(engine) == before


@pytest.mark.parametrize('seconds', [5.0, 4.999])
def test_explicit_hybrid_skips_provably_impossible_one_move_probe(seconds):
    engine = _safe_frontier()
    planner = ActionPlanner(ActionSearchBudget(1024, 24, 32, seconds),
                            strategy='probe_then_depth_first')
    result = planner.search(engine)
    probe, deep = planner.search_telemetry
    assert probe['structurally_skipped'] and probe['states_delta'] == 0
    assert result.candidates and deep['unique_candidates_delta'] > 0


def test_explicit_probe_strategy_respects_zero_move_depth():
    engine = FiveDEngine()
    before = engine_state_signature(engine)
    planner = ActionPlanner(ActionSearchBudget(1024, 24, 0, 5.0),
                            strategy='probe_then_depth_first')
    result = planner.search(engine)
    assert result.candidates == () and result.termination_reason == 'move_depth_budget'
    assert result.explored_states == 0
    assert all(phase['depth_limit'] == 0 for phase in planner.search_telemetry)
    assert engine_state_signature(engine) == before


@pytest.mark.parametrize('budget', [ActionSearchBudget(512, 16, 32, 1.0),
                                    ActionSearchBudget(1024, 24, 32, 4.999)])
def test_other_configured_minimax_budgets_keep_depth_first(monkeypatch, budget):
    monkeypatch.setattr(minimax.time, 'monotonic', lambda: 100.001)
    calls = []

    class RecordingPlanner:
        def __init__(self, node_budget, *, strategy, deadline):
            calls.append(strategy)

        def search(self, engine):
            return ActionSearchResult((), 0, 'move_depth_budget')

    monkeypatch.setattr(minimax, 'ActionPlanner', RecordingPlanner)
    ai = HardAI(ChessColor.WHITE, budget=budget)
    ai._start_time = 100.0
    ai._search_candidates(None)
    assert calls == ['depth_first']


def test_hard_fixed_successors_exhaust_without_recovery_and_reset():
    engine = _captured('hard20_fixed_successors_terminal_state')
    before = engine_state_signature(engine)
    planner = ActionPlanner(_PRODUCTION_HYBRID_BUDGET, strategy='probe_then_depth_first')
    result = planner.search(engine)
    assert result.candidates == () and result.termination_reason is None
    assert result.explored_states <= 1024
    assert engine_state_signature(engine) == before
    fresh = _captured('hard20_rewind_four_state')
    result = planner.search(fresh)
    assert result.candidates
    assert not planner._in_probe and not planner._defense_order_active


def test_single_move_probe_leaves_incomplete_moves_for_the_deep_phase(monkeypatch):
    engine = _safe_frontier()
    # Exercise the probe even though this quiet fixture can normally skip it.
    monkeypatch.setattr(planning, '_branches_cannot_defer_required_boards', lambda _: False)
    planner = ActionPlanner(_PRODUCTION_HYBRID_BUDGET, strategy='probe_then_depth_first')
    original = FiveDEngine.execute_action_move
    deep_incomplete_moves = []

    def observe(self, move, *args, **kwargs):
        result = original(self, move, *args, **kwargs)
        if result and not move.is_branching:
            remaining = self.get_required_action_boards()
            if planner._in_probe:
                assert not remaining
            elif remaining:
                deep_incomplete_moves.append(move)
        return result

    monkeypatch.setattr(FiveDEngine, 'execute_action_move', observe)
    result = planner.search(engine)
    assert result.candidates and deep_incomplete_moves
    probe, fallback = planner.search_telemetry
    assert probe['depth_cutoffs_delta'] > 0
    assert fallback['unique_candidates_delta'] > 0


@pytest.mark.parametrize('seconds', [5.0, 4.999])
def test_minimax_probe_and_deep_phase_share_global_limits(monkeypatch, seconds):
    engine = _safe_frontier()
    monkeypatch.setattr(planning, '_branches_cannot_defer_required_boards', lambda _: False)
    now = [100.0]
    monkeypatch.setattr(planning.time, 'monotonic', lambda: now[0])
    calls = []
    original = ActionPlanner._dfs

    def inspect(self, state, path, depth, tracker, candidates, failed, **kwargs):
        if depth == 0:
            calls.append((id(tracker), tracker.explored_states, self._uses_production_strategy))
            if kwargs.get('depth_limit') == 1:
                tracker.explored_states = 7
                now[0] = 101.01
                tracker.check_time(kwargs['local_deadline'])
                return False
        return original(self, state, path, depth, tracker, candidates, failed, **kwargs)

    monkeypatch.setattr(ActionPlanner, '_dfs', inspect)
    planner = ActionPlanner(ActionSearchBudget(1024, 24, 32, seconds),
                            strategy='probe_then_depth_first', deadline=105.0)
    result = planner.search(engine)
    assert result.candidates
    assert len(calls) == 2 and calls[0][0] == calls[1][0]
    assert calls[0][1:] == (0, True) and calls[1][1:] == (7, True)
    assert result.explored_states <= 1024 and len(result.candidates) <= 24
    assert planner._tracker.deadline == 105.0
