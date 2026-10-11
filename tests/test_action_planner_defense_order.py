"""Complete-Action regression for the captured 19-required-board failure."""
import gzip
import json
from pathlib import Path

import src.ai.action_planner as planning
from src.ai.action_planner import (
    AIActionPlan, ActionPlanner, _PRODUCTION_HYBRID_BUDGET,
    apply_action_plan, engine_state_signature,
)
from src.data.archive import GameArchive
from src.engine import FiveDEngine


def _captured():
    path = Path(__file__).parent / 'fixtures/easy20_nineteen_required_state.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(path.read_bytes())))
    del engine._replay_origin
    return engine


def test_large_defense_candidates_replay_and_strategy_does_not_leak():
    engine = _captured()
    before = engine_state_signature(engine)
    planner = ActionPlanner(_PRODUCTION_HYBRID_BUDGET)
    result = planner.search(engine)
    assert result.candidates
    assert result.explored_states <= 1024 and len(result.candidates) <= 24
    for path in result.candidates:
        assert len(path) <= 32
        child = engine.clone_for_simulation()
        apply_action_plan(child, AIActionPlan(engine.current_turn_color, path, before))
        assert child.action_history[-1].submitted
    assert engine_state_signature(engine) == before
    assert planner._defense_order_active
    fresh = FiveDEngine()
    assert planner.search(fresh).candidates
    assert not planner._defense_order_active


def test_late_defense_preparation_is_not_a_terminal_proof(monkeypatch):
    engine = _captured()
    before = engine_state_signature(engine)
    now = [0.0]
    monkeypatch.setattr(planning.time, 'monotonic', lambda: now[0])
    for name in ('prove_direct_threat', 'prove_required_board_threat', 'prove_required_board_immobile'):
        monkeypatch.setattr(planning, name, lambda *args: None)
    original = planning.RoyalRules.threats_against
    def delayed_threats(self, color):
        result = original(self, color)
        now[0] = 6.0
        return result
    monkeypatch.setattr(planning.RoyalRules, 'threats_against', delayed_threats)
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert not result.candidates and result.termination_reason == 'time_budget'
    assert result.failed_state_cache_hits == 0
    assert engine_state_signature(engine) == before
