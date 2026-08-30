"""Static/browser-contract coverage for safe P2P invite links."""
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


def test_invite_menu_assets_and_three_real_player_modes_remain_present(client):
    html = client.get("/?room=abc123").get_data(as_text=True)
    assert "同屏双人对弈" in html
    assert "创建在线房间" in html
    assert "加入在线房间" in html
    assert "startGame('pvp')" in html
    assert "createP2PRoom()" in html
    assert "joinP2PRoom()" in html
    assert 'id="p2p-join-label"' in html
    assert 'id="p2p-join-detail"' in html
    assert "/static/js/p2p_invite.js" in html


def test_invite_adapter_uses_text_content_and_never_injects_room_html(client):
    javascript = client.get("/static/js/p2p_invite.js").get_data(as_text=True)
    assert "textContent" in javascript
    assert "innerHTML" not in javascript
    assert "const ROOM_CODE_PATTERN = /^[A-Z0-9]{6}$/;" in javascript
    assert ".trim().toUpperCase()" in javascript
    assert "new URLSearchParams(search || '')" in javascript


def test_invite_url_builder_contains_room_code_only(client):
    javascript = client.get("/static/js/p2p_invite.js").get_data(as_text=True)
    start = javascript.index("function buildInviteURL")
    end = javascript.index("return Object.freeze", start)
    builder = javascript[start:end]
    assert "/?room=${encodeURIComponent(normalized)}" in builder
    assert "player_token" not in builder
    assert "p2pPlayerToken" not in builder


def test_invite_join_requires_explicit_click_and_reuses_only_stored_token(client):
    javascript = client.get("/static/js/p2p_invite.js").get_data(as_text=True)
    assert "const p2pInviteBaseJoin = joinP2PRoom;" in javascript
    assert "joinP2PRoom = async function(roomCodeOverride = null)" in javascript
    assert "normalizeRoomCode(roomCodeOverride) || roomCodeFromLocation()" in javascript
    assert "if (!roomCode) return p2pInviteBaseJoin();" in javascript
    assert "const saved = readStoredP2PSession(roomCode);" in javascript
    assert "room_code: roomCode" in javascript
    assert "player_token: saved?.player_token || null" in javascript
    assert "window.removeEventListener('load', p2pInviteBaseRecover);" in javascript
    assert "if (invitedRoom && !readStoredP2PSession(invitedRoom)) return;" in javascript


def test_invite_adapter_does_not_override_hotseat_start_or_gameplay_transport(client):
    invite_javascript = client.get("/static/js/p2p_invite.js").get_data(as_text=True)
    p2p_javascript = client.get("/static/js/p2p.js").get_data(as_text=True)

    # The invite layer changes only menu/join/status behavior.  It never
    # intercepts startGame('pvp') or canonical move submission.
    assert "startGame =" not in invite_javascript
    assert "executeCanonicalMove =" not in invite_javascript
    assert "submitAction =" not in invite_javascript
    assert "/api/game/" not in invite_javascript

    # Existing P2P gameplay overrides remain strictly transport-scoped.
    assert "if (mode !== 'p2p') return baseCanSelectSource" in p2p_javascript
    assert "if (mode !== 'p2p') return baseSelectSource" in p2p_javascript
    assert "if (mode !== 'p2p') return baseExecuteCanonicalMove" in p2p_javascript
    assert "if (mode !== 'p2p') return baseSubmitAction" in p2p_javascript
    assert "if (mode !== 'p2p') return baseBackToMenu" in p2p_javascript
