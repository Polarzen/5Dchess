"""The production one-Move probe must reach active rewinds before its deadline."""
import gzip
import json
from pathlib import Path

import pytest

from src.ai.action_planner import (
    ActionPlanner, _PRODUCTION_HYBRID_BUDGET, engine_state_signature,
    resolve_move_spec,
)
from src.data.archive import GameArchive
from src.engine import ActionRules, FiveDEngine, Position, Timeline
from src.utils.constants import ChessColor


def replay(engine, candidate):
    child = engine.clone_for_simulation()
    for spec in candidate:
        assert child.execute_action_move(resolve_move_spec(child, spec))
    assert child.submit_action(evaluate_outcome=False)
    assert child.action_history[-1].submitted
    return child


@pytest.mark.parametrize('track_repetition', [False, True])
def test_captured_easy54_timeout_has_complete_actions_in_primary_budget(track_repetition):
    path = Path(__file__).parent / 'fixtures/easy54_probe_starvation_state.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(path.read_bytes())))
    del engine._replay_origin  # Match the captured live Arena engine.
    assert len(engine.action_history) == 108
    assert len(engine.get_required_action_boards()) == 8
    before = engine_state_signature(engine)
    planner = ActionPlanner(_PRODUCTION_HYBRID_BUDGET, track_repetition=track_repetition)
    result = planner.search(engine)
    assert result.candidates
    assert result.explored_states <= 1024 and len(result.candidates) <= 24
    assert len(result.candidates[0]) == 1
    for candidate in result.candidates:
        replay(engine, candidate)
    assert engine_state_signature(engine) == before


def test_impossible_single_move_probe_keeps_multi_move_fallback():
    engine = FiveDEngine()
    manager = engine.timeline_manager
    for lane, owner in [(-1, ChessColor.BLACK), (1, ChessColor.WHITE)]:
        manager.timelines[lane] = Timeline(lane, owner=owner,
            positions={0: Position.initial(lane)})
    manager._next_positive_id, manager._next_negative_id = 2, -2
    manager.refresh_activity()
    engine.current_action = ActionRules.begin(ChessColor.WHITE, manager.timelines)
    before = engine_state_signature(engine)
    assert len(engine.get_required_action_boards()) == 3
    planner = ActionPlanner(_PRODUCTION_HYBRID_BUDGET)
    result = planner.search(engine)
    assert result.candidates and all(len(candidate) >= 2 for candidate in result.candidates)
    probe, fallback = planner.search_telemetry
    assert probe['unique_candidates_after'] == 0 and probe['depth_cutoffs_delta'] > 0
    assert fallback['unique_candidates_delta'] > 0
    replay(engine, result.candidates[0])
    assert engine_state_signature(engine) == before
