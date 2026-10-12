"""Restoring a file must leave it usable by the same AI planning boundary."""
from copy import deepcopy

import pytest

from src.ai.action_planner import ActionPlanner, ActionSearchBudget, apply_action_plan
from src.ai.hard_ai import HardAI
from src.data.archive import GameArchive
from src.engine import FiveDEngine
from src.engine.action_search import _clone_state_for_action_search


@pytest.mark.parametrize('strategy', ['depth_first', 'probe_then_depth_first'])
def test_restored_ai_search_matches_plain_engine_without_mutating_archive(strategy):
    plain = FiveDEngine()
    restored = GameArchive.restore(GameArchive.capture(plain))
    before = GameArchive.capture(restored)
    origin = restored._replay_origin
    budget = ActionSearchBudget(128, 4, 8, None)
    expected = ActionPlanner(budget, strategy=strategy).search(plain)
    actual = ActionPlanner(budget, strategy=strategy).search(restored)
    assert actual.candidates == expected.candidates
    assert actual.candidates
    assert GameArchive.capture(restored) == before
    assert restored._replay_origin is origin


def test_restored_hard_ai_can_resume_and_keep_replay_origin():
    engine = GameArchive.restore(GameArchive.capture(FiveDEngine()))
    origin = deepcopy(engine._replay_origin)
    ai = HardAI(engine.current_turn_color, search_depth=1,
                budget=ActionSearchBudget(128, 2, 8, None))
    plan = ai.plan_action(engine)
    apply_action_plan(engine, plan)
    assert engine.action_history[-1].submitted
    assert engine._replay_origin == origin


def test_archive_marker_does_not_mask_unknown_ai_state():
    engine = GameArchive.restore(GameArchive.capture(FiveDEngine()))
    engine.unknown_mutable_state = []
    with pytest.raises(RuntimeError, match='unknown_mutable_state'):
        ActionPlanner().search(engine)


def test_restored_root_copies_rule_state_once_without_copying_archive_metadata(monkeypatch):
    import src.engine.action_search as search
    engine = GameArchive.restore(GameArchive.capture(FiveDEngine()))
    origin = engine._replay_origin
    before = GameArchive.capture(engine)

    def forbidden_deepcopy(_):
        raise AssertionError('canonical restored root must not duplicate its archive')

    monkeypatch.setattr(search, 'deepcopy', forbidden_deepcopy)
    child = _clone_state_for_action_search(engine)
    assert not hasattr(child, '_replay_origin')
    position = child.get_current_position()
    position.board[0][0] = ''
    position.castling_rights.clear()
    position.unmoved_pawns.clear()
    child.timeline_manager.timelines.clear()
    child.current_action.submitted = True
    assert GameArchive.capture(engine) == before
    assert engine._replay_origin is origin
