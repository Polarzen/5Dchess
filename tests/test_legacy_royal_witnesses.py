"""Previously accepted witnesses must not hide a second same-board King.

Original captured states and old witnesses remain intact. Their former
positive benchmark expectations cannot override corrected canonical rules.
"""
import gzip
import json
from pathlib import Path

import pytest

from src.ai.action_planner import (
    AIActionPlan, ActionPlanner, InvalidActionPlanError, MoveSpec,
    _PRODUCTION_HYBRID_BUDGET, apply_action_plan, engine_state_signature, resolve_move_spec,
)
from src.data.archive import GameArchive
from src.engine import BoardCoord, RoyalRules, Square5D
from src.utils.constants import ChessColor


FIXTURES = Path(__file__).parent / 'fixtures'
WITNESSES = json.loads((FIXTURES / 'legacy_unsafe_king_witnesses.json').read_text())


def _engine(name):
    engine = GameArchive.restore(json.loads(gzip.decompress((FIXTURES / f'{name}.json.gz').read_bytes())))
    del engine._replay_origin
    return engine


def _square(values):
    lane, turn, side, x, y = values
    return Square5D(BoardCoord(lane, turn, ChessColor(side)), x, y)


@pytest.mark.parametrize('fixture', WITNESSES)
def test_legacy_witness_is_rejected_by_complete_royal_safety(fixture):
    engine = _engine(fixture)
    before = engine_state_signature(engine)
    specs = tuple(MoveSpec(_square(raw['source']), _square(raw['destination']))
                  for raw in WITNESSES[fixture]['specs'])
    with pytest.raises(InvalidActionPlanError):
        apply_action_plan(engine, AIActionPlan(engine.current_turn_color, specs, before))
    assert engine_state_signature(engine) == before
    child = engine.clone_for_simulation()
    if WITNESSES[fixture]['expected_failure'] == 'illegal_move':
        for spec in specs[:10]:
            assert child.execute_action_move(resolve_move_spec(child, spec))
        with pytest.raises(InvalidActionPlanError):
            resolve_move_spec(child, specs[10])
    else:
        for spec in specs:
            assert child.execute_action_move(resolve_move_spec(child, spec))
        assert not child.can_submit_action()
        threats = RoyalRules(child.timeline_manager.timelines).direct_threats_against(child.current_turn_color)
        assert any(t.king.timeline == -1 and (t.king.x, t.king.y) == (5, 6) for t in threats)
        assert not child.submit_action()


def test_four_required_snapshot_has_a_different_safe_primary_budget_action():
    engine = _engine('hard20_four_required_state')
    before = engine_state_signature(engine)
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert 0 < len(result.candidates) <= 24 and result.explored_states <= 1024
    child = engine.clone_for_simulation()
    apply_action_plan(child, AIActionPlan(engine.current_turn_color, result.candidates[0], before))
    assert child.action_history[-1].submitted
    assert engine_state_signature(engine) == before
