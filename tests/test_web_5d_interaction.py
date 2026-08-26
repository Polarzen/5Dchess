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

    javascript = client.get("/static/js/game.js").get_data(as_text=True)
    assert "/api/game/legal_moves_5d" in javascript
    assert "/api/game/move_5d" in javascript
    assert "/api/game/submit_action" in javascript


def test_web_ui_visible_labels_are_chinese(client):
    html = client.get("/").get_data(as_text=True)
    javascript = client.get("/static/js/game.js").get_data(as_text=True)

    for label in (
        "5D 象棋",
        "多时间线棋盘",
        "当前行动",
        "提交行动",
        "必须行动",
        "棋谱回放",
    ):
        assert label in html

    for label in (
        "当前玩家：",
        "当前时刻：",
        "对局进行中",
        "白方",
        "黑方",
        "活动时间线",
        "规范回合：",
        "本次行动步数",
    ):
        assert label in javascript

    for english_label in (
        "5D Chess",
        "Multiverse Board",
        "Submit Action",
        "Legacy AI compatibility",
        ">Present<",
        ">Required<",
        ">Movable<",
        ">Inactive<",
        ">Replay<",
    ):
        assert english_label not in html


def test_temporary_share_mode_requires_login_and_blocks_file_access(client, monkeypatch):
    monkeypatch.setenv("FIVED_CHESS_SHARE_MODE", "1")
    monkeypatch.setenv("FIVED_CHESS_SHARE_USER", "棋手")
    monkeypatch.setenv("FIVED_CHESS_SHARE_PASSWORD", "correct-password")

    protected = client.get("/")
    assert protected.status_code == 302
    assert protected.headers["Location"].endswith("/share/login")

    login_page = client.get("/share/login")
    assert login_page.status_code == 200
    assert "临时分享棋局" in login_page.get_data(as_text=True)

    rejected = client.post(
        "/share/login",
        data={"username": "棋手", "password": "wrong-password"},
    )
    assert rejected.status_code == 401
    assert "用户名或密码错误" in rejected.get_data(as_text=True)

    accepted = client.post(
        "/share/login",
        data={"username": "棋手", "password": "correct-password"},
    )
    assert accepted.status_code == 302
    assert accepted.headers["Location"].endswith("/")
    assert client.get("/").status_code == 200

    for endpoint in ("/api/game/save", "/api/game/load", "/api/replay/load"):
        response = client.post(endpoint, json={"filepath": "blocked.5dpgn"})
        assert response.status_code == 403
        assert "已禁用本机文件保存和加载功能" in response.get_json()["error"]


def test_start_state_serializes_canonical_present_board(client):
    state = _start_pvp(client)

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
