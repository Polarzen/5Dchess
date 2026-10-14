"""Local/AI save, continue and replay through the player-facing routes."""
import json
from pathlib import Path

import pytest

from src.ai import llm_client
from src.data.archive import GameArchive
from src.data.local_save import LocalSaveStore
from src.data.pgn_parser import FiveDPGN
from src.engine import FiveDEngine
from src.utils.constants import GameState
from src.web.app import app, _game_session
from tests.test_p2p_persistence import isolated
from tests.test_p2p_web import _pair


def store():
    return LocalSaveStore(app.config['P2P_SAVE_DIR'])


def pending_move():
    engine = _game_session['mode_instance'].engine
    position = engine.timeline_manager.get_timeline(0).get_position(0)
    move = next(move for move in engine.get_legal_moves(position)
                if (move.source.x, move.source.y, move.destination.x, move.destination.y) == (4, 6, 4, 4)
                and move.destination.board == move.source.board)
    assert engine.execute_action_move(move)


@pytest.mark.parametrize('mode', ['pvp', 'pve'])
def test_manual_save_catalog_restore_and_replay_preserve_pending_move(mode):
    client = app.test_client()
    assert client.post('/api/game/start', json={'mode': mode, 'difficulty': 'easy'}).status_code == 200
    pending_move()
    original = GameArchive.capture(_game_session['mode_instance'].engine)
    saved = client.post('/api/game/save', json={})
    assert saved.status_code == 200 and saved.json['saved']['mode'] == mode
    save_id = saved.json['saved']['save_id']
    path = store().path(save_id)
    assert path.exists() and path.parent == Path(app.config['P2P_SAVE_DIR']) / 'local'
    assert GameArchive.capture(_game_session['mode_instance'].engine) == original
    entries = client.get('/api/p2p/saves').json['saves']
    assert entries[0]['save_id'] == save_id
    assert client.post('/api/game/save', json={}).json['saved']['save_id'] == save_id
    assert len(list(path.parent.glob('*.5dpgn'))) == 1
    client.post('/api/game/start', json={'mode': 'pvp'})
    restored = client.post('/api/game/restore_saved', json={'save_id': save_id})
    assert restored.status_code == 200 and restored.json['mode'] == mode
    assert _game_session['ai_difficulty'] == 'easy'
    assert GameArchive.capture(_game_session['mode_instance'].engine) == original
    before = path.read_bytes()
    replay = client.post('/api/game/replay_saved', json={'save_id': save_id})
    assert replay.status_code == 200 and replay.json['total_moves'] == 1
    assert client.post('/api/replay/step', json={'action': 'end'}).status_code == 200
    assert GameArchive.capture(_game_session['mode_instance'].engine) == original
    assert path.read_bytes() == before


def test_new_game_gets_new_save_and_black_player_is_restored():
    client = app.test_client()
    client.post('/api/game/start', json={'mode': 'pve', 'difficulty': 'medium', 'player_color': 'black'})
    first = client.post('/api/game/save', json={}).json['saved']['save_id']
    client.post('/api/game/start', json={'mode': 'pvp'})
    second = client.post('/api/game/save', json={}).json['saved']['save_id']
    assert first != second
    restored = client.post('/api/game/restore_saved', json={'save_id': first})
    assert restored.json['mode'] == 'pve' and restored.json['player_color'] == 'black'


def test_failed_replace_preserves_saved_bytes_and_live_engine(monkeypatch):
    import src.data.pgn_parser as parser
    client = app.test_client()
    client.post('/api/game/start', json={'mode': 'pvp'})
    save_id = client.post('/api/game/save', json={}).json['saved']['save_id']
    path = store().path(save_id)
    before = path.read_bytes()
    pending_move()
    current = GameArchive.capture(_game_session['mode_instance'].engine)
    def fail(*args):
        raise PermissionError('test write denial')
    monkeypatch.setattr(parser.os, 'replace', fail)
    result = client.post('/api/game/save', json={})
    assert result.status_code == 503
    assert path.read_bytes() == before
    assert GameArchive.capture(_game_session['mode_instance'].engine) == current
    assert not list(path.parent.glob('.game-*.tmp'))


def test_parent_creation_failure_returns_false_without_losing_game(tmp_path):
    blocked = tmp_path / 'not-a-directory'
    blocked.write_text('keep', encoding='utf-8')
    assert not FiveDPGN.save(str(blocked / 'game.5dpgn'), FiveDEngine())
    assert blocked.read_text() == 'keep'


@pytest.mark.parametrize('path', ['/api/game/save', '/api/game/restore_saved', '/api/game/replay_saved'])
def test_remote_visitors_cannot_manage_host_files(path):
    response = app.test_client().post(path, json={}, headers={'CF-Connecting-IP': '198.51.100.2'})
    assert response.status_code == 403
    assert not store().directory.exists()


def test_invalid_or_corrupt_save_preserves_active_session():
    client = app.test_client()
    client.post('/api/game/start', json={'mode': 'pve', 'difficulty': 'easy'})
    current = _game_session['mode_instance']
    for save_id in (None, '../README', 'local-../../README'):
        assert client.post('/api/game/restore_saved', json={'save_id': save_id}).status_code == 400
        assert _game_session['mode_instance'] is current
    save_id = client.post('/api/game/save', json={}).json['saved']['save_id']
    store().path(save_id).write_text('{broken', encoding='utf-8')
    assert client.post('/api/game/replay_saved', json={'save_id': save_id}).status_code == 400
    assert client.get('/api/p2p/saves').json['unreadable'] == 1
    assert _game_session['mode_instance'] is current


def test_finished_local_game_is_saved_but_cannot_continue():
    client = app.test_client()
    client.post('/api/game/start', json={'mode': 'pvp'})
    _game_session['mode_instance'].engine.game_state = GameState.DRAW
    saved = client.post('/api/game/save', json={})
    assert saved.status_code == 200 and saved.json['saved']['game_state'] == 'DRAW'
    assert client.post('/api/game/restore_saved', json={'save_id': saved.json['saved']['save_id']}).status_code == 409


@pytest.mark.parametrize('invalid', [{'metadata': None, 'game': {}}, {'metadata': {'mode': 'pvp', 'date': None}, 'game': {}}])
def test_malformed_metadata_does_not_hide_valid_saves(invalid):
    client = app.test_client()
    client.post('/api/game/start', json={'mode': 'pvp'})
    save_id = client.post('/api/game/save', json={}).json['saved']['save_id']
    store().path('local-' + 'f' * 32).write_text(json.dumps(invalid), encoding='utf-8')
    catalog = client.get('/api/p2p/saves')
    assert catalog.status_code == 200 and catalog.json['unreadable'] == 1
    assert [saved['save_id'] for saved in catalog.json['saves']] == [save_id]


def test_local_saved_game_cannot_replace_online_room():
    client = app.test_client()
    client.post('/api/game/start', json={'mode': 'pvp'})
    save_id = client.post('/api/game/save', json={}).json['saved']['save_id']
    _pair()
    current = _game_session['mode_instance']
    assert client.post('/api/game/restore_saved', json={'save_id': save_id}).status_code == 409
    assert client.post('/api/game/save', json={}).status_code == 409
    assert _game_session['mode_instance'] is current


def test_llm_save_excludes_credentials_and_replay_works_without_key(monkeypatch, tmp_path):
    for field in ('API_KEY', 'BASE_URL', 'MODEL', 'TIMEOUT_SECONDS', 'MAX_REQUESTS'):
        monkeypatch.delenv('FIVE_D_CHESS_LLM_' + field, raising=False)
    config_path = tmp_path / 'llm.json'
    monkeypatch.setattr(llm_client, 'CONFIG_PATH', config_path)
    config_path.write_text(json.dumps({'api_key': 'local-save-fixture-only'}), encoding='utf-8')
    client = app.test_client()
    assert client.post('/api/game/start', json={'mode': 'pve', 'difficulty': 'llm'}).status_code == 200
    save_id = client.post('/api/game/save', json={}).json['saved']['save_id']
    text = store().path(save_id).read_text(encoding='utf-8')
    assert 'local-save-fixture-only' not in text and 'api_key' not in text
    config_path.unlink()
    assert client.post('/api/game/restore_saved', json={'save_id': save_id}).status_code == 400
    assert client.post('/api/game/replay_saved', json={'save_id': save_id}).status_code == 200
