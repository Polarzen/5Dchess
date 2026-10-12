"""Saved-game replay is read-only, exact and independent of SQL packages."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.data.archive import GameArchive
from src.engine import FiveDEngine
from src.utils.constants import GameState
from src.web.app import app, _game_session
import src.web.p2p as p2p
from tests.test_p2p_persistence import isolated, store
from tests.test_p2p_web import _pair
from tests.test_replay_storage_v2 import _two_move_action_engine


SAVE_ID = 'c' * 32


def open_replay(engine=None):
    engine = engine or _two_move_action_engine()
    store().save(SAVE_ID, engine)
    client = app.test_client()
    result = client.post('/api/p2p/replay', json={'save_id': SAVE_ID})
    assert result.status_code == 200, result.json
    return client, result.json, engine


def step(client, action, **kwargs):
    result = client.post('/api/replay/step', json={'action': action, **kwargs})
    assert result.status_code == 200, result.json
    return result.json


def test_saved_multitimeline_replay_keeps_submit_boundary_and_can_resume():
    client, state, final = open_replay()
    path = Path(app.config['P2P_SAVE_DIR']) / f'{SAVE_ID}.json'
    before = path.read_bytes()
    assert state['mode'] == 'replay' and state['current_index'] == 0
    assert state['total_moves'] == 2 and p2p._room is None
    first = step(client, 'forward')
    assert first['current_index'] == 1 and first['turn'] == 'white'
    assert len(_game_session['mode_instance'].engine.current_action.moves) == 1
    last = step(client, 'forward')
    assert last['turn'] == 'black' and last['action_counter'] == 1
    assert GameArchive.capture(_game_session['mode_instance'].engine) == GameArchive.capture(final)
    assert step(client, 'backward')['boards'] == first['boards']
    assert step(client, 'jump', index=0)['boards'] == state['boards']
    assert step(client, 'end')['boards'] == last['boards']
    step(client, 'start')  # Continuing uses the saved final state, not this frame.
    restored = client.post('/api/p2p/restore', json={'save_id': SAVE_ID})
    assert restored.status_code == 200 and restored.json['room_code']
    assert GameArchive.capture(_game_session['mode_instance'].engine) == GameArchive.capture(final)
    assert path.read_bytes() == before


def test_finished_save_is_replay_only():
    from tests.test_ai_terminal_scoring import tactical_position
    from tests.test_replay_storage_v2 import _play_spatial
    engine = tactical_position()
    GameArchive.set_replay_origin(engine)
    _play_spatial(engine, (6, 2), (6, 1))
    assert engine.game_state == GameState.CHECKMATE
    client, state, _ = open_replay(engine)
    assert state['game_state'] == 'PLAYING'
    assert state['total_moves'] == 1
    assert step(client, 'end')['game_state'] == 'CHECKMATE'
    assert not step(client, 'toggle')['is_playing']
    result = client.post('/api/p2p/restore', json={'save_id': SAVE_ID})
    assert result.status_code == 409 and result.json['code'] == 'game_finished'
    assert p2p._room is None and _game_session['mode'] == 'replay'
    assert step(client, 'backward')['game_state'] == 'PLAYING'


def test_empty_save_can_be_viewed_without_playback_loop():
    client, state, _ = open_replay(FiveDEngine())
    assert state['total_moves'] == 0
    assert not step(client, 'toggle')['is_playing']


def test_bad_history_or_corruption_does_not_replace_current_replay():
    client, _, _ = open_replay()
    current = _game_session['mode_instance']
    invalid = _two_move_action_engine()
    invalid.action_history.clear()
    store().save('d' * 32, invalid)
    result = client.post('/api/p2p/replay', json={'save_id': 'd' * 32})
    assert result.status_code == 409 and result.json['code'] == 'replay_unavailable'
    path = Path(app.config['P2P_SAVE_DIR']) / f'{SAVE_ID}.json'
    path.write_text('{broken', encoding='utf-8')
    for save_id in (SAVE_ID, '../README', None):
        result = client.post('/api/p2p/replay', json={'save_id': save_id})
        assert result.status_code == 409 and result.json['code'] == 'save_unavailable'
    assert _game_session['mode_instance'] is current
    assert path.read_text() == '{broken'


def test_replay_cannot_replace_online_room():
    host, _, _, _, _, _ = _pair()
    current = _game_session['mode_instance']
    result = host.post('/api/p2p/replay', json={'save_id': SAVE_ID})
    assert result.status_code == 409 and result.json['code'] == 'room_full'
    assert _game_session['mode_instance'] is current


def test_catalog_includes_older_games():
    engine = FiveDEngine()
    for index in range(22):
        store().save(f'{index:032x}', engine)
    result = app.test_client().get('/api/p2p/saves').json
    assert len(result['saves']) == 22
    assert result['unreadable'] == 0
    assert result['saves'] == sorted(result['saves'], key=lambda item: item['saved_at'], reverse=True)


def test_playback_ticks_are_idempotent_and_manual_controls_pause():
    client, _, _ = open_replay()
    assert step(client, 'toggle')['is_playing']
    assert step(client, 'tick', expected_index=0)['current_index'] == 1
    assert step(client, 'tick', expected_index=0)['current_index'] == 1
    assert not step(client, 'backward')['is_playing']
    assert step(client, 'tick', expected_index=0)['current_index'] == 0
    step(client, 'toggle')
    step(client, 'tick', expected_index=0)
    end = step(client, 'tick', expected_index=1)
    assert end['current_index'] == 2 and not end['is_playing']
    assert step(client, 'jump', index=-9)['current_index'] == 0
    assert step(client, 'jump', index=900)['current_index'] == 2
    for command in ({'action': 'jump', 'index': 'oops'}, {'action': 'unknown'}):
        assert client.post('/api/replay/step', json=command).status_code == 400


def test_startup_and_file_replay_without_sql_or_network(tmp_path):
    # Fail on attempted imports/connections, even if dev environment has SQL installed.
    code = '''
import importlib.abc, sys, socket
class NoSQL(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'mysql', 'sqlalchemy'}:
            raise AssertionError('Unexpected SQL dependency: ' + fullname)
sys.meta_path.insert(0, NoSQL())
def reject_connection(*args, **kwargs):
    raise AssertionError('Unexpected network connection')
socket.socket.connect = reject_connection
socket.create_connection = reject_connection
import src.main
from src.web.app import app
from src.data.online_save import OnlineSaveStore
from src.engine import FiveDEngine
engine = FiveDEngine()
assert engine.execute_move(engine.get_legal_moves()[0])
OnlineSaveStore(app.config['P2P_SAVE_DIR']).save('e' * 32, engine)
client = app.test_client()
assert client.get('/').status_code == 200
assert client.get('/api/p2p/saves').json['saves']
assert client.post('/api/p2p/replay', json={'save_id': 'e' * 32}).status_code == 200
assert client.post('/api/replay/step', json={'action': 'end'}).json['current_index'] == 1
'''
    env = {**os.environ, 'DB_PORT': 'unused-invalid-port', 'FIVE_D_CHESS_SAVE_DIR': str(tmp_path)}
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
