"""Regression coverage for browser-visible Action safety warnings."""
from __future__ import annotations

from src.web.app import _game_session, app


def test_frontier_repetition_is_visible_and_does_not_end_or_lock_game():
    from tests.test_frontier_repetition import play_cycle
    saved = _game_session.copy()
    try:
        with app.test_client() as client:
            assert client.post('/api/game/start', json={'mode': 'pvp'}).status_code == 200
            engine = _game_session['mode_instance'].engine
            play_cycle(engine, 2)
            state = client.get('/api/game/state').json
            assert state['repetition']['occurrences'] == 3
            assert state['repetition']['is_draw'] is False
            assert state['game_state'] == 'PLAYING'
            assert state['action']['movable_boards']
            assert not state['rule_warning']
            source = next(b['coord'] for b in state['boards'] if b['key'] == '0:8')
            moves = client.post('/api/game/legal_moves_5d', json={'board': source, 'x': 4, 'y': 6}).json['moves']
            move = next(m for m in moves if m['source']['board']['key'] == m['destination']['board']['key']
                        and m['destination']['y'] == 4)
            assert client.post('/api/game/move_5d', json=move).json['repetition'] is None
            assert client.post('/api/game/submit_action', json={}).json['repetition'] is None
    finally:
        _game_session.clear()
        _game_session.update(saved)


def test_action_rule_warning_reaches_browser_toast():
    app.config.update(TESTING=True)
    _game_session.update({
        "mode": None,
        "mode_instance": None,
        "ai_difficulty": "medium",
        "player_color": None,
    })

    warning = (
        "Action 合法性搜索达到安全上限 "
        "(time_budget, explored=4096)；为避免误判将杀/逼和，当前结果保持未决。"
    )

    try:
        with app.test_client() as client:
            started = client.post(
                "/api/game/start",
                json={"mode": "pvp", "difficulty": "medium", "player_color": "white"},
            )
            assert started.status_code == 200

            instance = _game_session["mode_instance"]
            instance.engine.rule_warning = warning

            state = client.get("/api/game/state")
            assert state.status_code == 200
            assert state.get_json()["rule_warning"] == warning

            javascript = client.get("/static/js/game.js").get_data(as_text=True)
            assert "surfaceRuleWarning();" in javascript
            assert "gameState?.rule_warning" in javascript
            assert "规则保护：${warning}" in javascript
            assert "if (warning === lastRuleWarning) return;" in javascript
    finally:
        _game_session.update({
            "mode": None,
            "mode_instance": None,
            "ai_difficulty": "medium",
            "player_color": None,
        })
