"""Regression coverage for browser-visible Action safety warnings."""
from __future__ import annotations

from src.web.app import _game_session, app


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
