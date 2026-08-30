"""Web multiverse UI/API regression coverage."""
from __future__ import annotations

import pytest

from src.web.app import _game_session, app


@pytest.fixture()
def client():
    app.config.update(TESTING=True)
    _game_session.update({
        "mode": None,
        "mode_instance": None,
        "ai_difficulty": "medium",
        "player_color": None,
    })
    with app.test_client() as test_client:
        yield test_client
    _game_session.update({
        "mode": None,
        "mode_instance": None,
        "ai_difficulty": "medium",
        "player_color": None,
    })


def _start_pvp(client):
    response = client.post(
        "/api/game/start",
        json={"mode": "pvp", "difficulty": "medium", "player_color": "white"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    return data


def test_index_is_multiverse_canvas_not_single_board(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="multiverse-viewport"' in html
    assert 'id="timeline-canvas"' in html
    assert 'id="timeline-links"' in html
    assert 'id="submit-action-btn"' in html
    assert 'id="board"' not in html

    # Local hotseat and online P2P are distinct, first-class menu entries.
    assert "startGame('pvp')" in html
    assert "同屏双人对弈" in html
    assert "Hotseat · 本地 PvP" in html
    assert "createP2PRoom()" in html
    assert "创建在线房间" in html
    assert "joinP2PRoom()" in html
    assert "加入在线房间" in html
    assert "Cloudflare Tunnel" in html

    javascript = client.get("/static/js/game.js").get_data(as_text=True)
    assert "/api/game/legal_moves_5d" in javascript
    assert "/api/game/move_5d" in javascript
    assert "/api/game/submit_action" in javascript

    # The online adapter must delegate every gameplay override back to the
    # ordinary browser implementation whenever the active mode is not P2P.
    p2p_javascript = client.get("/static/js/p2p.js").get_data(as_text=True)
    assert "if (mode !== 'p2p') return baseCanSelectSource" in p2p_javascript
    assert "if (mode !== 'p2p') return baseSelectSource" in p2p_javascript
    assert "if (mode !== 'p2p') return baseExecuteCanonicalMove" in p2p_javascript
    assert "if (mode !== 'p2p') return baseSubmitAction" in p2p_javascript
    assert "if (mode !== 'p2p') return baseBackToMenu" in p2p_javascript


def test_start_state_serializes_canonical_present_board(client):
    state = _start_pvp(client)

    assert state["mode"] == "pvp"
    assert "p2p" not in state
    assert "room_code" not in state
    assert "player_token" not in state
    assert state["game_state"] == "PLAYING"
    assert state["turn"] == "white"
    assert len(state["boards"]) == 1
    board = state["boards"][0]

    assert board["key"] == "0:0"
    assert board["coord"] == {
        "key": "0:0",
        "timeline": 0,
        "turn": 0,
        "side": "white",
        "time_point": 0,
    }
    assert board["playable"] is True
    assert board["historical"] is False
    assert board["timeline_active"] is True
    assert board["is_present"] is True
    assert board["is_required"] is True
    assert board["is_movable"] is True

    assert state["present"]["boards"][0]["key"] == "0:0"
    assert state["action"]["required_boards"][0]["key"] == "0:0"
    assert state["action"]["movable_boards"][0]["key"] == "0:0"
    assert state["action"]["can_submit"] is False


def test_piece_selection_returns_boardcoord_aware_moves(client):
    state = _start_pvp(client)
    board = state["boards"][0]

    response = client.post(
        "/api/game/legal_moves_5d",
        json={"board": board["coord"], "x": 4, "y": 6},
    )
    assert response.status_code == 200
    moves = response.get_json()["moves"]
    assert len(moves) == 2

    for move in moves:
        assert move["source"]["board"]["key"] == "0:0"
        assert move["source"]["x"] == 4
        assert move["source"]["y"] == 6
        assert move["destination"]["board"]["key"] == "0:0"
        assert move["color"] == "white"
        assert move["is_cross_timeline"] is False
        assert move["is_branching"] is False


def test_pvp_move_stays_inside_action_until_explicit_submit(client):
    state = _start_pvp(client)
    board = state["boards"][0]
    moves = client.post(
        "/api/game/legal_moves_5d",
        json={"board": board["coord"], "x": 4, "y": 6},
    ).get_json()["moves"]
    e2e4 = next(move for move in moves if move["destination"]["y"] == 4)

    moved_response = client.post(
        "/api/game/move_5d",
        json={
            "source": e2e4["source"],
            "destination": e2e4["destination"],
            "promotion": e2e4["promotion"],
        },
    )
    assert moved_response.status_code == 200
    moved = moved_response.get_json()
    assert moved["success"] is True

    # Board-local successor advances to BLACK, but the global Action still
    # belongs to WHITE until the player explicitly submits.
    assert moved["turn"] == "white"
    assert moved["action"]["color"] == "white"
    assert moved["action"]["move_count"] == 1
    assert moved["action"]["can_submit"] is True
    assert moved["action"]["required_boards"] == []
    assert len(moved["boards"]) == 2

    old_board = next(item for item in moved["boards"] if item["key"] == "0:0")
    new_board = next(item for item in moved["boards"] if item["key"] == "0:1")
    assert old_board["historical"] is True
    assert new_board["playable"] is True
    assert new_board["coord"]["side"] == "black"
    assert new_board["is_present"] is True

    submitted_response = client.post("/api/game/submit_action", json={})
    assert submitted_response.status_code == 200
    submitted = submitted_response.get_json()
    assert submitted["success"] is True
    assert submitted["turn"] == "black"
    assert submitted["action"]["color"] == "black"
    assert submitted["action"]["move_count"] == 0
    assert submitted["action"]["can_submit"] is False
    assert submitted["action"]["required_boards"][0]["key"] == "0:1"

    # The same browser now controls Black: hotseat has no fixed player-color
    # authorization layer. Black completes e7-e5 and explicitly submits too.
    black_board = next(item for item in submitted["boards"] if item["playable"])
    black_moves = client.post(
        "/api/game/legal_moves_5d",
        json={"board": black_board["coord"], "x": 4, "y": 1},
    ).get_json()["moves"]
    e7e5 = next(move for move in black_moves if move["destination"]["y"] == 3)
    black_moved_response = client.post(
        "/api/game/move_5d",
        json={
            "source": e7e5["source"],
            "destination": e7e5["destination"],
            "promotion": e7e5["promotion"],
        },
    )
    assert black_moved_response.status_code == 200
    black_moved = black_moved_response.get_json()
    assert black_moved["success"] is True
    assert black_moved["turn"] == "black"
    assert black_moved["action"]["color"] == "black"
    assert black_moved["action"]["move_count"] == 1
    assert black_moved["action"]["can_submit"] is True

    black_submitted_response = client.post("/api/game/submit_action", json={})
    assert black_submitted_response.status_code == 200
    black_submitted = black_submitted_response.get_json()
    assert black_submitted["success"] is True
    assert black_submitted["turn"] == "white"
    assert black_submitted["move_counter"] == 2
    assert black_submitted["action"]["color"] == "white"
    assert black_submitted["action"]["move_count"] == 0


def test_historical_board_cannot_be_reused_as_action_source(client):
    state = _start_pvp(client)
    source_board = state["boards"][0]
    moves = client.post(
        "/api/game/legal_moves_5d",
        json={"board": source_board["coord"], "x": 4, "y": 6},
    ).get_json()["moves"]
    move = next(item for item in moves if item["destination"]["y"] == 4)
    moved = client.post(
        "/api/game/move_5d",
        json={"source": move["source"], "destination": move["destination"]},
    ).get_json()

    historical = next(item for item in moved["boards"] if item["key"] == "0:0")
    response = client.post(
        "/api/game/legal_moves_5d",
        json={"board": historical["coord"], "x": 3, "y": 6},
    )
    assert response.status_code == 200
    assert response.get_json()["moves"] == []


def test_web_save_reload_replay_and_continue_roundtrip(client, tmp_path):
    state = _start_pvp(client)
    source_board = state["boards"][0]
    moves = client.post(
        "/api/game/legal_moves_5d",
        json={"board": source_board["coord"], "x": 4, "y": 6},
    ).get_json()["moves"]
    first_move = next(item for item in moves if item["destination"]["y"] == 4)
    assert client.post(
        "/api/game/move_5d",
        json={"source": first_move["source"], "destination": first_move["destination"]},
    ).get_json()["success"]
    assert client.post("/api/game/submit_action", json={}).get_json()["success"]

    filepath = tmp_path / "web-e2e.5dpgn"
    saved = client.post("/api/game/save", json={"filepath": str(filepath)})
    assert saved.status_code == 200
    saved_state = saved.get_json()
    assert saved_state["turn"] == "black"
    assert saved_state["move_counter"] == 1

    replayed = client.post("/api/replay/load", json={"filepath": str(filepath)})
    assert replayed.status_code == 200
    assert replayed.get_json()["current_index"] == 0
    replay_end = client.post("/api/replay/step", json={"action": "end"}).get_json()
    assert replay_end["move_counter"] == 1
    assert replay_end["turn"] == "black"

    loaded = client.post("/api/game/load", json={"filepath": str(filepath)})
    assert loaded.status_code == 200
    loaded_state = loaded.get_json()
    assert loaded_state["mode"] == "pvp"
    assert loaded_state["turn"] == "black"
    black_board = next(board for board in loaded_state["boards"] if board["playable"])
    black_moves = client.post(
        "/api/game/legal_moves_5d",
        json={"board": black_board["coord"], "x": 4, "y": 1},
    ).get_json()["moves"]
    reply = next(item for item in black_moves if item["destination"]["y"] == 3)
    continued = client.post(
        "/api/game/move_5d",
        json={"source": reply["source"], "destination": reply["destination"]},
    ).get_json()
    assert continued["success"]
    assert continued["move_counter"] == 2
