"""Durable submission, local recovery authority and crash/restart regressions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from src.data.archive import GameArchive
from src.data.online_save import OnlineSaveStore
import src.web.p2p as p2p
from src.web.app import app, _game_session
from tests.test_p2p_web import FakeClock, _pair, _credentials, _move_pawn, _reset_state


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    clock = FakeClock()
    monkeypatch.setattr(p2p, '_clock', clock)
    monkeypatch.setitem(app.config, 'P2P_SAVE_DIR', str(tmp_path / 'saves'))
    _reset_state()
    yield clock
    _reset_state()


def store():
    return OnlineSaveStore(app.config['P2P_SAVE_DIR'])


def pending_pawn(client, auth, x=4, y=6, target=4):
    state = client.post('/api/p2p/state', json=auth).json
    board = next(b for b in state['boards'] if b['is_movable'])
    moves = client.post('/api/p2p/legal_moves', json={**auth, 'board': board['coord'], 'x': x, 'y': y}).json['moves']
    move = next(m for m in moves if m['destination']['y'] == target)
    assert client.post('/api/p2p/move', json={**auth, **move}).status_code == 200


def test_checkpoint_only_advances_after_submit_and_recovery_reinvites():
    host, guest, created, _, auth, guest_auth = _pair()
    save_id = created['p2p']['saved']['save_id']
    pending_pawn(host, auth)
    assert store().load(save_id)[0].move_counter == 0
    submitted = host.post('/api/p2p/submit', json={**auth, 'expected_action_counter': 0})
    assert submitted.status_code == 200
    saved = GameArchive.capture(_game_session['mode_instance'].engine)
    assert store().load(save_id)[1]['action_counter'] == 1
    pending_pawn(guest, guest_auth, y=1, target=3)
    _reset_state()  # Same disk, fresh server memory.
    restored = host.post('/api/p2p/restore', json={'save_id': save_id})
    assert restored.status_code == 200
    assert restored.json['room_code'] != created['room_code']
    assert restored.json['player_token'] != created['player_token']
    assert restored.json['turn'] == 'black'
    assert GameArchive.capture(_game_session['mode_instance'].engine) == saved
    assert guest.post('/api/p2p/state', json=guest_auth).status_code == 404
    assert host.post('/api/p2p/submit', json=_credentials(restored.json)).status_code == 409
    rejoined = guest.post('/api/p2p/join', json={'room_code': restored.json['room_code']}).json
    after = _move_pawn(guest, _credentials(rejoined), 1, 3)
    assert after['action_counter'] == 2
    assert after['p2p']['saved']['action_counter'] == 2
    text = (Path(app.config['P2P_SAVE_DIR']) / f'{save_id}.json').read_text()
    for token in (created['player_token'], restored.json['player_token'], rejoined['player_token']):
        assert token not in text


def test_replace_failure_preserves_disk_and_pending_turn_then_retry(monkeypatch):
    host, _, created, _, auth, _ = _pair()
    pending_pawn(host, auth)
    original = _game_session['mode_instance'].engine
    original_archive = GameArchive.capture(original)
    path = Path(app.config['P2P_SAVE_DIR']) / f"{created['p2p']['saved']['save_id']}.json"
    before = path.read_bytes()
    with monkeypatch.context() as patch:
        def fail_replace(*_args):
            raise OSError('simulated disk failure')
        patch.setattr('src.data.online_save.os.replace', fail_replace)
        failed = host.post('/api/p2p/submit', json=auth)
    assert failed.status_code == 503 and failed.json['code'] == 'save_failed'
    assert path.read_bytes() == before
    assert not list(path.parent.glob('*.tmp'))
    assert _game_session['mode_instance'].engine is original
    assert GameArchive.capture(original) == original_archive
    assert host.post('/api/p2p/state', json=auth).json['p2p']['save_error']
    retried = host.post('/api/p2p/submit', json=auth)
    assert retried.status_code == 200 and retried.json['action_counter'] == 1
    assert not retried.json['p2p']['save_error']


def test_failed_initial_save_does_not_create_half_room(monkeypatch):
    def failure(*_args):
        raise PermissionError('unwritable')
    monkeypatch.setattr(OnlineSaveStore, 'save', failure)
    result = app.test_client().post('/api/p2p/create', json={})
    assert result.status_code == 503
    assert p2p._room is None and _game_session['mode_instance'] is None


@pytest.mark.parametrize('remote,host,headers', [
    ('192.168.1.9', 'localhost', {}),
    ('127.0.0.1', 'public.trycloudflare.com', {}),
    ('127.0.0.1', 'localhost', {'CF-Ray': 'test'}),
    ('127.0.0.1', 'localhost', {'X-Forwarded-For': '127.0.0.1'}),
    ('127.0.0.1', 'localhost', {'Forwarded': 'for=127.0.0.1'}),
    ('127.0.0.1', 'localhost', {'Origin': 'https://untrusted.example'}),
    ('127.0.0.1', 'localhost', {'Sec-Fetch-Site': 'cross-site'}),
])
def test_recovery_and_listing_never_allow_public_or_forwarded_host(remote, host, headers):
    client = app.test_client()
    for path, method in [('/api/p2p/saves', 'GET'), ('/api/p2p/restore', 'POST')]:
        result = client.open(path, method=method, json={'save_id': 'a' * 32},
                             headers={'Host': host, **headers}, environ_overrides={'REMOTE_ADDR': remote})
        assert result.status_code == 403
        assert result.json['code'] == 'host_required'
    assert p2p._room is None


def test_corrupt_or_missing_save_and_path_traversal_preserve_original():
    host, _, created, _, auth, _ = _pair()
    host.post('/api/p2p/leave', json=auth)
    save_id = created['p2p']['saved']['save_id']
    path = Path(app.config['P2P_SAVE_DIR']) / f'{save_id}.json'
    raw = json.loads(path.read_text())
    raw['payload']['game']['move_counter'] = 90
    path.write_text(json.dumps(raw))
    broken = path.read_bytes()
    assert host.get('/api/p2p/saves').json == {'saves': [], 'unreadable': 1}
    for invalid in [save_id, '../README', 'a' * 32, None, {}]:
        result = host.post('/api/p2p/restore', json={'save_id': invalid})
        assert result.status_code == 409
        assert p2p._room is None
    assert path.read_bytes() == broken


def test_expiry_keeps_save_and_catalog_does_not_overwrite_previous_game(isolated):
    host, _, created, _, auth, _ = _pair()
    saved = _move_pawn(host, auth, 6, 4)
    isolated.advance(300)
    first = host.post('/api/p2p/state', json=auth).json['p2p']
    assert first['opponent_status'] == 'offline'
    assert first['opponent_retention_remaining'] == pytest.approx(308)
    isolated.advance(5)
    second = host.post('/api/p2p/state', json=auth).json['p2p']
    assert first['state_version'] == second['state_version']
    assert second['opponent_retention_remaining'] == pytest.approx(303)
    isolated.advance(609)
    assert host.post('/api/p2p/state', json=auth).status_code == 410
    assert store().load(saved['p2p']['saved']['save_id'])[1]['action_counter'] == 1
    new = host.post('/api/p2p/create', json={}).json
    assert len(host.get('/api/p2p/saves').json['saves']) == 2
    blocked = host.post('/api/p2p/restore', json={'save_id': created['p2p']['saved']['save_id']})
    assert blocked.status_code == 409
    assert p2p._room['code'] == new['room_code']


def test_late_duplicate_submission_does_not_submit_a_later_turn():
    host, guest, _, _, auth, guest_auth = _pair()
    _move_pawn(host, auth, 6, 4)
    _move_pawn(guest, guest_auth, 1, 3)
    pending_pawn(host, auth, x=3)
    result = host.post('/api/p2p/submit', json={**auth, 'expected_action_counter': 0})
    assert result.status_code == 409 and result.json['code'] == 'action_conflict'
    assert len(_game_session['mode_instance'].engine.action_history) == 2
    assert _game_session['mode_instance'].engine.can_submit_action()


def test_multitimeline_multimove_action_archive_is_exact():
    from tests.test_replay_storage_v2 import _two_move_action_engine
    engine = _two_move_action_engine()
    store().save('b' * 32, engine)
    restored, info = store().load('b' * 32)
    assert info['action_counter'] == 1 and info['move_counter'] == 2
    assert GameArchive.capture(restored) == GameArchive.capture(engine)


def test_real_process_kill_restart_and_continue(tmp_path):
    """Two HTTP clients on ONE machine; intentionally not a remote acceptance."""
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'FIVE_D_CHESS_SAVE_DIR': str(tmp_path / 'process-saves'), 'PYTHONUTF8': '1'}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    processes = []

    def call(path, data=None):
        request = urllib.request.Request(origin + path, data=json.dumps(data).encode() if data is not None else None,
                                         headers={'Content-Type': 'application/json'})
        try:
            with opener.open(request, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def launch():
        process = subprocess.Popen([sys.executable, '-X', 'utf8', str(root / 'scripts/run_p2p_server.py'),
                                    '--host', '127.0.0.1', '--port', str(port)], cwd=root, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        processes.append(process)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            assert process.poll() is None, 'isolated server exited during startup'
            try:
                if call('/api/p2p/saves')[0] == 200:
                    return process
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(.1)
        pytest.fail('isolated server startup timed out')

    def move(auth, y, target):
        code, state = call('/api/p2p/state', auth)
        assert code == 200
        board = next(b for b in state['boards'] if b['is_movable'])
        code, legal = call('/api/p2p/legal_moves', {**auth, 'board': board['coord'], 'x': 4, 'y': y})
        assert code == 200
        selected = next(m for m in legal['moves'] if m['destination']['y'] == target)
        assert call('/api/p2p/move', {**auth, **selected})[0] == 200

    try:
        first = launch()
        _, created = call('/api/p2p/create', {})
        _, joined = call('/api/p2p/join', {'room_code': created['room_code']})
        auth, guest_auth = _credentials(created), _credentials(joined)
        move(auth, 6, 4)
        code, submitted = call('/api/p2p/submit', auth)
        assert code == 200 and submitted['action_counter'] == 1
        move(guest_auth, 1, 3)  # Deliberately not submitted before abrupt kill.
        first.kill()
        first.wait(timeout=10)
        launch()
        assert call('/api/p2p/state', auth)[0] == 404
        code, restored = call('/api/p2p/restore', {'save_id': submitted['p2p']['saved']['save_id']})
        assert code == 200 and restored['boards'] == submitted['boards']
        assert restored['action_counter'] == restored['move_counter'] == 1
        _, joined = call('/api/p2p/join', {'room_code': restored['room_code']})
        move(_credentials(joined), 1, 3)
        code, continued = call('/api/p2p/submit', _credentials(joined))
        assert code == 200 and continued['p2p']['saved']['action_counter'] == 2
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
