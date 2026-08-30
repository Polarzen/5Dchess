"""End-to-end regression coverage for the online two-player room transport."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
import threading

import pytest

import src.web.p2p as p2p_module
from src.web import app
from src.web.app import _game_session


web_app_module = importlib.import_module("src.web.app")


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds: float):
        self.value += seconds


def _credentials(payload: dict) -> dict:
    return {
        "room_code": payload["room_code"],
        "player_token": payload["player_token"],
    }


def _reset_state():
    p2p_module._room = None
    p2p_module._expired_room_codes.clear()
    _game_session.update({
        "mode": None,
        "mode_instance": None,
        "ai_difficulty": "medium",
        "player_color": None,
    })


@pytest.fixture(autouse=True)
def isolated_p2p(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(p2p_module, "_clock", clock)
    _reset_state()
    yield clock
    _reset_state()


def _pair():
    host = app.test_client()
    guest = app.test_client()
    created_response = host.post("/api/p2p/create", json={})
    assert created_response.status_code == 200
    created = created_response.get_json()
    joined_response = guest.post(
        "/api/p2p/join", json={"room_code": created["room_code"]}
    )
    assert joined_response.status_code == 200
    joined = joined_response.get_json()
    return host, guest, created, joined, _credentials(created), _credentials(joined)


def _move_pawn(client, auth, source_y, destination_y):
    state = client.post("/api/p2p/state", json=auth).get_json()
    board = next(board for board in state["boards"] if board["playable"])
    legal_response = client.post(
        "/api/p2p/legal_moves",
        json={**auth, "board": board["coord"], "x": 4, "y": source_y},
    )
    assert legal_response.status_code == 200
    move = next(
        move for move in legal_response.get_json()["moves"]
        if move["destination"]["y"] == destination_y
    )
    moved = client.post(
        "/api/p2p/move",
        json={
            **auth,
            "source": move["source"],
            "destination": move["destination"],
            "promotion": move["promotion"],
        },
    )
    assert moved.status_code == 200
    submitted = client.post("/api/p2p/submit", json=auth)
    assert submitted.status_code == 200
    return submitted.get_json()


def test_p2p_room_two_clients_complete_one_move_each():
    host, guest, created, joined, host_auth, guest_auth = _pair()

    assert len(created["room_code"]) == 6
    assert created["player_color"] == "white"
    assert created["p2p"]["opponent_status"] == "not_connected"
    assert joined["player_color"] == "black"
    assert joined["p2p"]["opponent_status"] == "connected"

    blocked = host.get("/api/game/state")
    assert blocked.status_code == 409
    assert blocked.get_json()["code"] == "p2p_room_active"

    full = app.test_client().post(
        "/api/p2p/join", json={"room_code": created["room_code"]}
    )
    assert full.status_code == 409
    assert full.get_json()["code"] == "room_full"

    invalid = guest.post(
        "/api/p2p/state",
        json={"room_code": created["room_code"], "player_token": "invalid"},
    )
    assert invalid.status_code == 401
    assert invalid.get_json()["code"] == "invalid_token"

    guest_wrong_turn = guest.post(
        "/api/p2p/legal_moves",
        json={**guest_auth, "board": joined["boards"][0]["coord"], "x": 4, "y": 1},
    )
    assert guest_wrong_turn.status_code == 409
    assert guest_wrong_turn.get_json()["code"] == "not_your_turn"

    after_white = _move_pawn(host, host_auth, 6, 4)
    assert after_white["turn"] == "black"
    after_black = _move_pawn(guest, guest_auth, 1, 3)
    assert after_black["turn"] == "white"
    assert after_black["move_counter"] == 2


def test_black_heartbeat_prevents_timeout(isolated_p2p):
    host, guest, _, _, host_auth, guest_auth = _pair()
    isolated_p2p.advance(7)
    assert guest.post("/api/p2p/state", json=guest_auth).status_code == 200
    isolated_p2p.advance(7)
    state = host.post("/api/p2p/state", json=host_auth).get_json()
    assert state["p2p"]["opponent_status"] == "connected"


def test_black_timeout_reconnect_grace_and_release(isolated_p2p):
    host, guest, created, _, host_auth, guest_auth = _pair()
    initial_version = host.post("/api/p2p/state", json=host_auth).get_json()["p2p"]["state_version"]
    isolated_p2p.advance(p2p_module.PLAYER_LEASE_SECONDS + 0.1)
    offline = host.post("/api/p2p/state", json=host_auth).get_json()
    assert offline["p2p"]["opponent_status"] == "offline"
    offline_version = offline["p2p"]["state_version"]
    assert offline_version > initial_version

    reserved = app.test_client().post(
        "/api/p2p/join", json={"room_code": created["room_code"]}
    )
    assert reserved.status_code == 409
    assert reserved.get_json()["code"] == "room_full"

    isolated_p2p.advance(20)
    reconnected = guest.post("/api/p2p/join", json=guest_auth)
    assert reconnected.status_code == 200
    assert reconnected.get_json()["reconnected"] is True
    assert reconnected.get_json()["player_color"] == "black"
    assert reconnected.get_json()["p2p"]["state_version"] > offline_version

    # Keep WHITE alive while BLACK passes the lease+grace boundary.
    assert host.post("/api/p2p/state", json=host_auth).status_code == 200
    isolated_p2p.advance(30)
    assert host.post("/api/p2p/state", json=host_auth).status_code == 200
    isolated_p2p.advance(9)
    released = host.post("/api/p2p/state", json=host_auth).get_json()
    assert released["p2p"]["opponent_status"] == "not_connected"
    old_token = guest_auth["player_token"]
    invalid = guest.post("/api/p2p/state", json=guest_auth)
    assert invalid.status_code == 401
    assert invalid.get_json()["code"] == "invalid_token"
    joined_again = guest.post("/api/p2p/join", json={"room_code": created["room_code"]})
    assert joined_again.status_code == 200
    assert joined_again.get_json()["player_color"] == "black"
    assert joined_again.get_json()["player_token"] != old_token


def test_host_drop_grace_recovery_and_state_versions(isolated_p2p):
    host, guest, _, _, host_auth, guest_auth = _pair()
    initial_version = guest.post("/api/p2p/state", json=guest_auth).get_json()["p2p"]["state_version"]
    isolated_p2p.advance(p2p_module.PLAYER_LEASE_SECONDS + 0.1)
    dropped = guest.post("/api/p2p/state", json=guest_auth).get_json()
    assert dropped["p2p"]["opponent_status"] == "offline"
    dropped_version = dropped["p2p"]["state_version"]
    assert dropped_version > initial_version
    unchanged = guest.post("/api/p2p/state", json=guest_auth).get_json()
    assert unchanged["p2p"]["state_version"] == dropped_version

    isolated_p2p.advance(10)
    recovered = host.post("/api/p2p/join", json=host_auth).get_json()
    assert recovered["reconnected"] is True
    assert recovered["player_color"] == "white"
    recovered_state = guest.post("/api/p2p/state", json=guest_auth).get_json()
    assert recovered_state["p2p"]["opponent_status"] == "connected"
    assert recovered_state["p2p"]["state_version"] > dropped_version


def test_stale_host_cleanup_expires_room_and_allows_create(isolated_p2p):
    host = app.test_client()
    created = host.post("/api/p2p/create", json={}).get_json()
    auth = _credentials(created)
    isolated_p2p.advance(
        p2p_module.PLAYER_LEASE_SECONDS + p2p_module.RECONNECT_GRACE_SECONDS + 1
    )
    replacement = app.test_client().post("/api/p2p/create", json={})
    assert replacement.status_code == 200
    stale = host.post("/api/p2p/state", json=auth)
    assert stale.status_code == 410
    assert stale.get_json()["code"] == "room_expired"


def test_opponent_offline_blocks_mutation_and_malformed_errors_have_no_traceback(isolated_p2p):
    host, _, _, _, host_auth, _ = _pair()
    online_state = host.post("/api/p2p/state", json=host_auth).get_json()
    board = next(board for board in online_state["boards"] if board["playable"])
    moves = host.post(
        "/api/p2p/legal_moves",
        json={**host_auth, "board": board["coord"], "x": 4, "y": 6},
    ).get_json()["moves"]
    e2e4 = next(move for move in moves if move["destination"]["y"] == 4)

    isolated_p2p.advance(p2p_module.PLAYER_LEASE_SECONDS + 0.1)
    blocked = host.post(
        "/api/p2p/move",
        json={
            **host_auth,
            "source": e2e4["source"],
            "destination": e2e4["destination"],
            "promotion": e2e4["promotion"],
        },
    )
    assert blocked.status_code == 409
    assert blocked.get_json()["code"] == "opponent_offline"

    malformed = host.post("/api/p2p/state", data="[]", content_type="application/json")
    assert malformed.status_code == 400
    assert malformed.get_json()["code"] == "invalid_request"
    assert "traceback" not in malformed.get_data(as_text=True).lower()


def test_room_not_found_and_action_not_submittable_are_clear_4xx():
    missing = app.test_client().post(
        "/api/p2p/state",
        json={"room_code": "ZZZZZZ", "player_token": "invalid"},
    )
    assert missing.status_code == 404
    assert missing.get_json()["code"] == "room_not_found"

    host, _, _, _, host_auth, _ = _pair()
    cannot_submit = host.post("/api/p2p/submit", json=host_auth)
    assert cannot_submit.status_code == 409
    assert cannot_submit.get_json()["code"] == "action_not_submittable"


def test_normal_leave_and_legacy_mutation_guard(isolated_p2p):
    host, guest, _, _, host_auth, guest_auth = _pair()
    legacy_mutations = (
        ("/api/game/start", {"mode": "pvp"}),
        ("/api/game/move_5d", {}),
        ("/api/game/submit_action", {}),
        ("/api/replay/load", {}),
    )
    for path, payload in legacy_mutations:
        blocked = app.test_client().post(path, json=payload)
        assert blocked.status_code == 409
        assert blocked.get_json()["code"] == "p2p_room_active"

    left_guest = guest.post("/api/p2p/leave", json=guest_auth)
    assert left_guest.status_code == 200
    assert left_guest.get_json()["closed"] is False
    state = host.post("/api/p2p/state", json=host_auth).get_json()
    assert state["p2p"]["opponent_status"] == "not_connected"
    closed = host.post("/api/p2p/leave", json=host_auth)
    assert closed.status_code == 200
    assert closed.get_json()["closed"] is True
    missing = host.post("/api/p2p/state", json=host_auth)
    assert missing.status_code == 404
    assert missing.get_json()["code"] == "room_not_found"


def test_internal_error_is_generic_and_does_not_expose_token(isolated_p2p, monkeypatch):
    host = app.test_client()
    created = host.post("/api/p2p/create", json={}).get_json()
    auth = _credentials(created)
    token = auth["player_token"]
    logged = []
    monkeypatch.setattr(p2p_module.logger, "error", logged.append)
    _game_session["mode_instance"] = None
    response = host.post("/api/p2p/state", json=auth)
    assert response.status_code == 500
    assert response.get_json()["code"] == "internal_error"
    assert token not in response.get_data(as_text=True)
    assert logged
    assert all(token not in message for message in logged)


def test_two_concurrent_black_joins_allocate_exactly_one_seat():
    created = app.test_client().post("/api/p2p/create", json={}).get_json()
    barrier = threading.Barrier(2)

    def join_once():
        client = app.test_client()
        barrier.wait(timeout=2)
        response = client.post(
            "/api/p2p/join", json={"room_code": created["room_code"]}
        )
        return response.status_code, response.get_json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: join_once(), range(2)))

    assert sorted(status for status, _payload in results) == [200, 409]
    success = next(payload for status, payload in results if status == 200)
    rejected = next(payload for status, payload in results if status == 409)
    assert success["player_color"] == "black"
    assert rejected["code"] == "room_full"
    assert p2p_module._room["players"]["black"] == success["player_token"]


def test_legacy_mutation_holds_room_lock_against_concurrent_create(monkeypatch):
    legacy_in_handler = threading.Event()
    release_legacy = threading.Event()
    create_started = threading.Event()
    create_finished = threading.Event()
    original_engine = web_app_module.FiveDEngine

    def paused_legacy_engine(*args, **kwargs):
        legacy_in_handler.set()
        assert release_legacy.wait(timeout=2)
        return original_engine(*args, **kwargs)

    monkeypatch.setattr(web_app_module, "FiveDEngine", paused_legacy_engine)

    def start_legacy_game():
        return app.test_client().post("/api/game/start", json={"mode": "pvp"})

    def create_p2p_room():
        create_started.set()
        response = app.test_client().post("/api/p2p/create", json={})
        create_finished.set()
        return response

    with ThreadPoolExecutor(max_workers=2) as executor:
        legacy_future = executor.submit(start_legacy_game)
        assert legacy_in_handler.wait(timeout=2)
        create_future = executor.submit(create_p2p_room)
        assert create_started.wait(timeout=2)
        assert not create_finished.wait(timeout=0.2)
        release_legacy.set()
        legacy_response = legacy_future.result(timeout=2)
        create_response = create_future.result(timeout=2)

    assert legacy_response.status_code == 200
    assert create_response.status_code == 200
    created = create_response.get_json()
    assert p2p_module._room["code"] == created["room_code"]
    assert _game_session["mode_instance"].engine is not None
    assert app.test_client().post(
        "/api/p2p/state", json=_credentials(created)
    ).status_code == 200


def test_web_menu_loads_resilient_p2p_client_entrypoints():
    app.config.update(TESTING=True)
    client = app.test_client()
    html = client.get("/").get_data(as_text=True)
    assert "createP2PRoom()" in html
    assert "joinP2PRoom()" in html
    assert "/static/js/p2p.js" in html

    javascript = client.get("/static/js/p2p.js").get_data(as_text=True)
    assert "/api/p2p/create" in javascript
    assert "/api/p2p/join" in javascript
    assert "/api/p2p/state" in javascript
    assert "setInterval(pollP2PState, 1200)" in javascript
    assert "p2pPollInFlight" in javascript
    assert "P2P_POLL_MAX_BACKOFF_MS" in javascript
    assert "Opponent offline" in javascript
    assert "Waiting for opponent" in javascript
    assert "P2P 连接已恢复" in javascript
    assert "P2P 会话已结束" in javascript
    assert "clearStoredP2PSession" in javascript
    assert "recoverStoredP2PSession" in javascript
    assert "state_version" in javascript
