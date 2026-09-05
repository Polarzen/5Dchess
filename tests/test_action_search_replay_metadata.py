"""Regression coverage for archive-decorated ActionSearch roots."""
from copy import deepcopy

import pytest

from src.ai.action_planner import engine_state_signature
from src.data.archive import GameArchive
from src.engine.action_search import ActionSearch
from src.engine.engine import FiveDEngine
from tests.test_action_search_simulation_clone import LegacyDeepcopyActionSearch


def _limits():
    return {"max_states": 256, "max_depth": 16, "max_seconds": None}


def test_replay_origin_search_matches_legacy_deepcopy_and_preserves_source():
    engine = FiveDEngine()
    origin = GameArchive.set_replay_origin(engine)
    before_state = engine_state_signature(engine)
    before_origin = deepcopy(origin)

    expected = LegacyDeepcopyActionSearch(**_limits()).find_legal_action(engine)
    actual = ActionSearch(**_limits()).find_legal_action(engine)

    assert actual == expected
    assert engine_state_signature(engine) == before_state
    assert engine._replay_origin == before_origin
    assert engine._replay_origin is origin


def test_replay_origin_partial_completion_matches_legacy_deepcopy():
    engine = FiveDEngine()
    GameArchive.set_replay_origin(engine)
    position = engine.get_current_position()
    move = engine.get_legal_moves(position)[0]
    assert engine.execute_action_move(move)
    before_state = engine_state_signature(engine)
    before_origin = deepcopy(engine._replay_origin)

    expected = LegacyDeepcopyActionSearch(**_limits()).find_legal_completion(engine)
    actual = ActionSearch(**_limits()).find_legal_completion(engine)

    assert actual == expected
    assert engine_state_signature(engine) == before_state
    assert engine._replay_origin == before_origin


def test_replay_origin_does_not_mask_other_unknown_dynamic_engine_state():
    engine = FiveDEngine()
    GameArchive.set_replay_origin(engine)
    engine.unmodeled_mutable_state = []

    with pytest.raises(RuntimeError, match="unmodeled_mutable_state"):
        ActionSearch(**_limits()).find_legal_action(engine)
