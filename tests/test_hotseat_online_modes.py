"""Regression coverage for switching between local hotseat and online P2P."""
from __future__ import annotations

import pytest

import src.web.p2p as p2p_module
from src.web import app
from src.web.app import _game_session


def _reset_state() -> None:
    p2p_module._room = None
    p2p_module._expired_room_codes.clear()
    _game_session.update({
        "mode": None,
        "mode_instance": None,
        "ai_difficulty": "medium",
        "player_color": None,
    })


@pytest.fixture(autouse=True)
def isolated_modes():
    app.config.update(TESTING=True)
    _reset_state()
    yield
    _reset_state()


def _auth(payload: dict) -> dict:
    return {
        "room_code": payload["room_code"],
        "player_token": payload["player_token"],
    }


def test_online_leave_then_hotseat_has_no_p2p_identity_or_room_requirement():
    client = app.test_client()
    created_response = client.post("/api/p2p/create", json={})
    assert created_response.status_code == 200
    created = created_response.get_json()
    assert created["mode"] == "p2p"

    left = client.post("/api/p2p/leave", json=_auth(created))
    assert left.status_code == 200
    assert left.get_json()["closed"] is True
    assert p2p_module._room is None

    hotseat_response = client.post(
        "/api/game/start",
        json={"mode": "pvp", "difficulty": "medium", "player_color": "white"},
    )
    assert hotseat_response.status_code == 200
    hotseat = hotseat_response.get_json()
    assert hotseat["mode"] == "pvp"
    assert hotseat["turn"] == "white"
    assert "p2p" not in hotseat
    assert "room_code" not in hotseat
    assert "player_token" not in hotseat
    assert p2p_module._room is None

    board = hotseat["boards"][0]
    legal = client.post(
        "/api/game/legal_moves_5d",
        json={"board": board["coord"], "x": 4, "y": 6},
    )
    assert legal.status_code == 200
    assert legal.get_json()["moves"]


def test_hotseat_then_online_replaces_local_session_and_preserves_p2p_auth():
    host = app.test_client()
    local_response = host.post(
        "/api/game/start",
        json={"mode": "pvp", "difficulty": "medium", "player_color": "white"},
    )
    assert local_response.status_code == 200
    local = local_response.get_json()
    assert local["mode"] == "pvp"
    assert p2p_module._room is None

    # Browser back-to-menu is client-side for hotseat. Creating an online room
    # must therefore safely replace the previous local server session.
    created_response = host.post("/api/p2p/create", json={})
    assert created_response.status_code == 200
    created = created_response.get_json()
    assert created["mode"] == "p2p"
    assert created["player_color"] == "white"
    assert created["p2p"]["opponent_status"] == "not_connected"
    assert p2p_module._room is not None

    guest = app.test_client()
    joined_response = guest.post(
        "/api/p2p/join",
        json={"room_code": created["room_code"]},
    )
    assert joined_response.status_code == 200
    joined = joined_response.get_json()
    assert joined["mode"] == "p2p"
    assert joined["player_color"] == "black"
    assert joined["player_token"] != created["player_token"]

    # Online mode still requires authenticated P2P endpoints and blocks the
    # unauthenticated local mutation API while the room is active.
    blocked = host.post("/api/game/submit_action", json={})
    assert blocked.status_code == 409
    assert blocked.get_json()["code"] == "p2p_room_active"

    invalid = guest.post(
        "/api/p2p/state",
        json={"room_code": created["room_code"], "player_token": "invalid"},
    )
    assert invalid.status_code == 401
    assert invalid.get_json()["code"] == "invalid_token"
