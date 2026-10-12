"""Later submitted Actions are exact witnesses for earlier replay boundaries."""
from dataclasses import replace
import gzip
import json
from pathlib import Path

import pytest

from src.data.archive import GameArchive
from src.engine import FiveDEngine
from src.modes.replay import ReplayMode
from src.utils.constants import GameState


def recorded_game(partial=False):
    engine = FiveDEngine()
    snapshots = [GameArchive.capture(engine)]
    for x, source_y, target_y in [(4, 6, 4), (4, 1, 3), (3, 6, 4)]:
        move = next(move for move in engine.get_legal_moves()
                    if move.is_spatial and move.from_x == move.to_x == x
                    and move.from_y == source_y and move.to_y == target_y)
        assert engine.execute_action_move(move)
        if not (partial and x == 3):
            assert engine.submit_action()
        snapshots.append(GameArchive.capture(engine))
    return engine, snapshots


@pytest.mark.parametrize('partial', [False, True])
def test_replay_uses_later_action_witnesses_and_still_evaluates_last_submit(monkeypatch, partial):
    engine, expected = recorded_game(partial)
    calls = []
    original = FiveDEngine._evaluate_multiverse_game_result

    def checked(self):
        calls.append(len(self.action_history))
        return original(self)

    monkeypatch.setattr(FiveDEngine, '_evaluate_multiverse_game_result', checked)
    replay = ReplayMode()
    replay.load_from_engine(engine, strict=True)
    assert calls == [len(engine.action_history)]
    assert replay.snapshots == expected


def test_invalid_later_action_cannot_serve_as_an_outcome_witness(monkeypatch):
    engine, _ = recorded_game()
    original = engine.action_history[1].moves[0]
    invalid = replace(original, destination=original.source)
    engine.action_history[1].moves[0] = invalid
    engine.move_history[1] = invalid
    calls = []

    def terminal_prior(self):
        calls.append(len(self.action_history))
        self.game_state = GameState.CHECKMATE

    monkeypatch.setattr(FiveDEngine, '_check_multiverse_game_result', terminal_prior)
    with pytest.raises(ValueError, match='terminal Action'):
        ReplayMode().load_from_engine(engine, strict=True)
    assert calls == [1]


def test_legacy_moves_fall_back_to_original_outcome_check(monkeypatch):
    engine, expected = recorded_game()
    original = FiveDEngine._evaluate_multiverse_game_result
    calls = []

    def checked(self):
        calls.append(len(self.action_history))
        return original(self)

    monkeypatch.setattr(FiveDEngine, '_evaluate_multiverse_game_result', checked)
    # Emulate history recorded under older local move rules. Canonical
    # submission and final exact-state comparison still apply as before.
    monkeypatch.setattr(FiveDEngine, 'get_legal_moves_from_square_to_boards', lambda *args: [])
    replay = ReplayMode()
    replay.load_from_engine(engine, strict=True)
    assert calls == [1, 2, 3]
    assert replay.snapshots == expected


def test_old_unsafe_history_is_still_rejected_at_royal_safe_submission():
    path = Path(__file__).parent / 'fixtures/hard20_twenty_three_required_state.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(path.read_bytes())))
    with pytest.raises(ValueError, match='Replay Action submit failed'):
        ReplayMode().load_from_engine(engine, strict=True)
