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
from src.engine.engine import FiveDEngine
from src.utils.constants import ChessColor


def _captured(name):
    path = Path(__file__).parent / 'fixtures' / f'{name}.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(path.read_bytes())))
    del engine._replay_origin
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
    assert [call[1:] for call in calls] == [('depth_first', 105.0)] * 2
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
    engine = _captured('hard20_six_required_state')
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
def test_absolute_deadline_includes_clone_preparation(monkeypatch, seconds):
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
    result = ActionPlanner(ActionSearchBudget(1024, 24, 32, seconds), strategy='depth_first',
                           deadline=101.0).search(engine)
    assert result.candidates == ()
    assert result.termination_reason == 'time_budget'
    assert result.explored_states == 0
    assert engine_state_signature(engine) == before


@pytest.mark.parametrize('fixture', ['hard20_four_required_state', 'hard20_six_required_state'])
def test_hard_captured_root_returns_canonical_action_with_primary_budget(fixture):
    engine = _captured(fixture)
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
