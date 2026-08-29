"""End-to-end regression coverage for the online two-player room transport."""
from __future__ import annotations

import src.web.p2p as p2p_module
from src.web import app
from src.web.app import _game_session


def _credentials(created_or_joined: dict) -> dict:
    return {
        "room_code": created_or_joined["room_code"],
        "player_token": created_or_joined["player_token"],
    }


def _reset_state():
    p2p_module._room = None
    _game_session.update({
        "mode": None,
        "mode_instance": None,
        "ai_difficulty": "medium",
        "player_color": None,
    })


def test_p2p_room_two_clients_complete_one_move_each():
    app.config.update(TESTING=True)
    _reset_state()
    host = app.test_client()
    guest = app.test_client()

    try:
        created_response = host.post("/api/p2p/create", json={})
        assert created_response.status_code == 200
        created = created_response.get_json()
        assert created["success"] is True
        assert len(created["room_code"]) == 6
        assert created["player_color"] == "white"
        assert created["p2p"]["opponent_connected"] is False
        assert created["p2p"]["can_act"] is False
        host_auth = _credentials(created)

        # While an online room exists, legacy unauthenticated game endpoints
        # cannot be used to bypass the room's player-token checks.
        blocked = host.get("/api/game/state")
        assert blocked.status_code == 409

        waiting = host.post(
            "/api/p2p/legal_moves",
            json={**host_auth, "board": created["boards"][0]["coord"], "x": 4, "y": 6},
        )
        assert waiting.status_code == 409
        assert "等待第二位玩家" in waiting.get_json()["error"]

        joined_response = guest.post(
            "/api/p2p/join",
            json={"room_code": created["room_code"]},
        )
        assert joined_response.status_code == 200
        joined = joined_response.get_json()
        assert joined["success"] is True
        assert joined["player_color"] == "black"
        assert joined["p2p"]["opponent_connected"] is True
        assert joined["p2p"]["can_act"] is False
        guest_auth = _credentials(joined)

        full = app.test_client().post(
            "/api/p2p/join",
            json={"room_code": created["room_code"]},
        )
        assert full.status_code == 409
        assert full.get_json()["error"] == "房间已满"

        invalid = guest.post(
            "/api/p2p/state",
            json={"room_code": created["room_code"], "player_token": "invalid"},
        )
        assert invalid.status_code == 401

        # Guest cannot act during WHITE's Action.
        guest_wrong_turn = guest.post(
            "/api/p2p/legal_moves",
            json={**guest_auth, "board": joined["boards"][0]["coord"], "x": 4, "y": 1},
        )
        assert guest_wrong_turn.status_code == 409
        assert guest_wrong_turn.get_json()["error"] == "当前是对手回合"

        host_state = host.post("/api/p2p/state", json=host_auth).get_json()
        assert host_state["p2p"]["can_act"] is True
        white_board = next(board for board in host_state["boards"] if board["playable"])
        white_moves = host.post(
            "/api/p2p/legal_moves",
            json={**host_auth, "board": white_board["coord"], "x": 4, "y": 6},
        ).get_json()["moves"]
        e2e4 = next(move for move in white_moves if move["destination"]["y"] == 4)

        moved_white = host.post(
            "/api/p2p/move",
            json={
                **host_auth,
                "source": e2e4["source"],
                "destination": e2e4["destination"],
                "promotion": e2e4["promotion"],
            },
        )
        assert moved_white.status_code == 200
        assert moved_white.get_json()["action"]["can_submit"] is True

        submitted_white = host.post("/api/p2p/submit", json=host_auth)
        assert submitted_white.status_code == 200
        assert submitted_white.get_json()["turn"] == "black"

        black_state = guest.post("/api/p2p/state", json=guest_auth).get_json()
        assert black_state["turn"] == "black"
        assert black_state["player_color"] == "black"
        assert black_state["p2p"]["can_act"] is True
        black_board = next(board for board in black_state["boards"] if board["playable"])
        black_moves = guest.post(
            "/api/p2p/legal_moves",
            json={**guest_auth, "board": black_board["coord"], "x": 4, "y": 1},
        ).get_json()["moves"]
        e7e5 = next(move for move in black_moves if move["destination"]["y"] == 3)

        moved_black = guest.post(
            "/api/p2p/move",
            json={
                **guest_auth,
                "source": e7e5["source"],
                "destination": e7e5["destination"],
                "promotion": e7e5["promotion"],
            },
        )
        assert moved_black.status_code == 200
        assert moved_black.get_json()["action"]["can_submit"] is True
        submitted_black = guest.post("/api/p2p/submit", json=guest_auth)
        assert submitted_black.status_code == 200
        assert submitted_black.get_json()["turn"] == "white"
        assert submitted_black.get_json()["move_counter"] == 2

        left_guest = guest.post("/api/p2p/leave", json=guest_auth)
        assert left_guest.status_code == 200
        assert left_guest.get_json()["closed"] is False
        host_after_leave = host.post("/api/p2p/state", json=host_auth).get_json()
        assert host_after_leave["p2p"]["opponent_connected"] is False

        closed = host.post("/api/p2p/leave", json=host_auth)
        assert closed.status_code == 200
        assert closed.get_json()["closed"] is True
        assert host.post("/api/p2p/state", json=host_auth).status_code == 404
    finally:
        _reset_state()


def test_web_menu_loads_p2p_client_entrypoints():
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
