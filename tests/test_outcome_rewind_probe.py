"""Exact unknown-outcome captures must yield royal-safe Actions in 3 seconds."""
import gzip
import json
from pathlib import Path

import pytest

from src.ai.action_planner import MoveSpec, engine_state_signature, resolve_move_spec
from src.data.archive import GameArchive
from src.engine import ActionRules, ActionSearch, OutcomeRules
from src.utils.constants import GameState


def captured(action=45, color='black'):
    path = Path(__file__).parent / 'fixtures' / f'outcome_action_{action}_{color}.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(path.read_bytes())))
    del engine._replay_origin
    return engine


@pytest.mark.parametrize('action,color', [(45, 'black'), (72, 'white'), (76, 'white'), (92, 'white')])
def test_captured_outcome_budget_warning_now_has_canonical_witness(action, color):
    engine = captured(action, color)
    before = engine_state_signature(engine)
    search = ActionSearch()
    assert (search.max_seconds, search.max_states, search.max_depth) == (3.0, 4096, 64)
    result = search.find_legal_action(engine)
    assert result.has_legal_action and not result.exhausted
    assert len(result.witness) == 1 and result.witness[0].is_branching
    assert result.explored_states <= 4096
    child = engine.clone_for_simulation()
    for move in result.witness:
        assert child.execute_action_move(resolve_move_spec(child, MoveSpec.from_move(move)))
    assert child.can_submit_action()
    assert child.submit_action(evaluate_outcome=False)
    assert engine_state_signature(engine) == before
    engine.rule_warning = 'old warning'
    assert OutcomeRules.evaluate(engine) is None
    assert engine.rule_warning is None and engine.game_state == GameState.PLAYING


def test_failed_or_locally_interrupted_probe_keeps_deep_search(monkeypatch):
    import src.engine.action_search as module
    from tests.test_action_search_simulation_clone import _multi_required_engine
    engine = _multi_required_engine()
    # Earlier same-color boards admit the root rewind probe; both probe and
    # fallback still use canonical move generation and submission.
    for lane in engine.timeline_manager.timelines.values():
        original = lane.positions[0]
        latest = original.copy()
        latest.time_point = 2
        lane.add_position(latest)
    engine.current_action = ActionRules.begin(engine.current_turn_color, engine.timeline_manager.timelines)
    # Force only the new one-second probe slice to expire during preparation.
    now = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    def slow_preparation(state, interrupted):
        now[0] = 101.1
        assert interrupted()
        return None
    monkeypatch.setattr(module, 'fixed_successor_attackers', slow_preparation)
    search = ActionSearch()
    before = engine_state_signature(engine)
    result = search.find_legal_action(engine)
    assert result.has_legal_action and not result.exhausted
    assert len(result.witness) >= 2
    assert ActionSearch._state_key(engine) not in search._failed_states
    assert engine_state_signature(engine) == before


def test_probe_global_deadline_still_means_unknown(monkeypatch):
    import src.engine.action_search as module
    engine = captured()
    now = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    def slow_preparation(state, interrupted):
        now[0] = 103.1
        assert interrupted()
        return None
    monkeypatch.setattr(module, 'fixed_successor_attackers', slow_preparation)
    search = ActionSearch()
    result = search.find_legal_action(engine)
    assert not result.has_legal_action and result.termination_reason == 'time_budget'
    assert ActionSearch._state_key(engine) not in search._failed_states


def test_probe_cannot_accept_progress_without_royal_safe_submit(monkeypatch):
    engine = captured()
    search = ActionSearch(max_states=16, max_seconds=None)
    calls = []
    def reject_unsafe(action, timelines):
        calls.append(action)
        return False
    monkeypatch.setattr(ActionRules, 'can_submit', reject_unsafe)
    search._reset_search()
    required = set(engine.get_required_action_boards())
    movable = ActionRules.movable_boards(engine.current_action, engine.timeline_manager.timelines)
    result = search._probe_present_rewind(engine, required, sorted(movable, key=lambda b: b.timeline))
    assert result is None and calls
    assert not search._failed_states


@pytest.mark.parametrize('states,has_action', [(0, False), (1, False), (2, True)])
def test_probe_respects_state_budget_and_accepts_witness_at_boundary(states, has_action):
    result = ActionSearch(max_states=states).find_legal_action(captured())
    assert result.has_legal_action == has_action
    assert result.explored_states <= states
    if not has_action:
        assert result.termination_reason == 'state_budget'


def test_zero_depth_still_cannot_probe_a_move():
    result = ActionSearch(max_depth=0).find_legal_action(captured())
    assert not result.has_legal_action and result.termination_reason == 'depth_limit'
