"""Focused coverage for bounded Web and P2P port selection."""
from __future__ import annotations

import importlib
import os
import socket
import sys

import pytest

from src.web import port_utils
from src.web.app import P2P_READINESS_PATH, app


def _ephemeral_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((port_utils.DEFAULT_HOST, 0))
        return sock.getsockname()[1]


def test_default_selection_constants_and_preferred_free_port():
    assert port_utils.DEFAULT_HOST == "127.0.0.1"
    assert port_utils.DEFAULT_PORT == 5050
    assert port_utils.DEFAULT_PORT_END == 5099
    preferred = _ephemeral_port()
    assert port_utils.select_port(preferred_port=preferred) == preferred


def test_probe_reports_occupied_then_released_socket():
    port = _ephemeral_port()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((port_utils.DEFAULT_HOST, port))
        sock.listen(1)
        assert not port_utils.is_port_available(port_utils.DEFAULT_HOST, port)
    finally:
        sock.close()
    assert port_utils.is_port_available(port_utils.DEFAULT_HOST, port)


def test_selection_skips_one_occupied_preferred_port():
    preferred = _ephemeral_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((port_utils.DEFAULT_HOST, preferred))
        sock.listen(1)
        assert port_utils.select_port(preferred_port=preferred) == preferred + 1


def test_selection_skips_one_and_two_occupied_candidates(monkeypatch):
    occupied = {62000, 62001}
    checked: list[int] = []

    def fake_probe(_host: str, port: int) -> bool:
        checked.append(port)
        return port not in occupied

    monkeypatch.setattr(port_utils, "is_port_available", fake_probe)
    assert port_utils.select_port(preferred_port=62000) == 62002
    assert checked == [62000, 62001, 62002]


def test_each_skipped_port_emits_concise_info():
    checked: list[int] = []
    messages: list[str] = []

    def fake_probe(_host: str, port: int) -> bool:
        checked.append(port)
        return port == 62002

    original_probe = port_utils.is_port_available
    try:
        port_utils.is_port_available = fake_probe
        assert port_utils.select_port(
            preferred_port=62000,
            log=messages.append,
        ) == 62002
    finally:
        port_utils.is_port_available = original_probe

    assert checked == [62000, 62001, 62002]
    assert messages == [
        "Web port 62000 unavailable; trying next",
        "Web port 62001 unavailable; trying next",
    ]


def test_selection_exhaustion_names_searched_range(monkeypatch):
    checked: list[int] = []
    monkeypatch.setattr(
        port_utils,
        "is_port_available",
        lambda _host, port: checked.append(port) or False,
    )

    with pytest.raises(port_utils.PortSelectionError, match="62000-62049"):
        port_utils.select_port(preferred_port=62000)
    assert checked == list(range(62000, 62050))


def test_explicit_window_clamps_at_maximum_port(monkeypatch):
    checked: list[int] = []
    monkeypatch.setattr(
        port_utils,
        "is_port_available",
        lambda _host, port: checked.append(port) or False,
    )

    with pytest.raises(port_utils.PortSelectionError, match="65535-65535"):
        port_utils.select_port(preferred_port=65535)
    assert checked == [65535]


def test_main_web_port_override_propagates(monkeypatch):
    main_module = importlib.import_module("src.main")
    captured: list[tuple[str, int | None]] = []
    monkeypatch.setattr(
        main_module,
        "run_web",
        lambda host=port_utils.DEFAULT_HOST, port=None: captured.append((host, port)),
    )
    monkeypatch.setattr(sys, "argv", ["main.py", "--web", "--port", "61234"])
    main_module.main()
    assert captured == [(port_utils.DEFAULT_HOST, 61234)]


def test_run_server_logs_actual_selected_url_and_uses_it(monkeypatch):
    app_calls: list[dict] = []
    log_messages: list[str] = []
    app_module = importlib.import_module("src.web.app")
    monkeypatch.setattr(app_module, "select_port", lambda *args, **kwargs: 61235)
    monkeypatch.setattr(app_module.logger, "info", log_messages.append)
    monkeypatch.setattr(
        app_module.app,
        "run",
        lambda **kwargs: app_calls.append(kwargs),
    )

    app_module.run_server(port=61234, debug=False)

    assert app_calls == [{
        "host": "127.0.0.1",
        "port": 61235,
        "debug": False,
        "use_reloader": False,
    }]
    assert any("http://127.0.0.1:61235" in message for message in log_messages)


def test_run_server_default_debug_and_p2p_strict_both_disable_reloader(monkeypatch):
    app_module = importlib.import_module("src.web.app")
    calls: list[dict] = []
    monkeypatch.setattr(app_module, "select_port", lambda *args, **kwargs: 61239)
    monkeypatch.setattr(app_module.app, "run", lambda **kwargs: calls.append(kwargs))

    app_module.run_server(port=61238)
    app_module.run_server(
        port=61240,
        debug=False,
        strict_port=True,
        launch_id="p2p-test-id",
    )

    assert calls == [
        {
            "host": "127.0.0.1",
            "port": 61239,
            "debug": True,
            "use_reloader": False,
        },
        {
            "host": "127.0.0.1",
            "port": 61240,
            "debug": False,
            "use_reloader": False,
        },
    ]
    app_module._launch_readiness_id = None


def test_run_server_wraps_final_bind_race(monkeypatch):
    app_module = importlib.import_module("src.web.app")
    monkeypatch.setattr(app_module, "select_port", lambda *args, **kwargs: 61238)
    monkeypatch.setattr(
        app_module.app,
        "run",
        lambda **kwargs: (_ for _ in ()).throw(OSError("address in use")),
    )

    with pytest.raises(RuntimeError, match="竞争条件"):
        app_module.run_server(port=61238, debug=False)


@pytest.mark.parametrize("failure", [OSError("address in use"), SystemExit(1)])
def test_run_server_translates_bind_and_nonzero_exit_failures(monkeypatch, failure):
    app_module = importlib.import_module("src.web.app")
    monkeypatch.setattr(app_module, "select_port", lambda *args, **kwargs: 61241)

    def fail(**_kwargs):
        raise failure

    monkeypatch.setattr(app_module.app, "run", fail)
    with pytest.raises(RuntimeError, match="http://127.0.0.1:61241") as raised:
        app_module.run_server(port=61241, debug=False, launch_id="failure-id")
    assert "竞争" in str(raised.value)


def test_run_server_allows_clean_system_exit(monkeypatch):
    app_module = importlib.import_module("src.web.app")
    clean_exit = SystemExit(0)
    monkeypatch.setattr(
        app_module,
        "select_port",
        lambda *args, **kwargs: 61242,
    )
    monkeypatch.setattr(
        app_module.app,
        "run",
        lambda **_kwargs: (_ for _ in ()).throw(clean_exit),
    )

    with pytest.raises(SystemExit) as raised:
        app_module.run_server(port=61242, debug=False)
    assert raised.value is clean_exit


def test_readiness_is_disabled_without_launch_identity_and_ignores_request_echo(monkeypatch):
    app_module = importlib.import_module("src.web.app")
    monkeypatch.setattr(app_module, "_launch_readiness_id", None)
    before = app_module._game_session.copy()

    response = app_module.app.test_client().get(
        P2P_READINESS_PATH,
        query_string={"launch_id": "attacker-controlled"},
    )

    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"
    assert "attacker-controlled" not in response.get_data(as_text=True)
    assert app_module._game_session == before


def test_readiness_returns_exact_identity_and_process_pid_without_game_mutation(monkeypatch):
    app_module = importlib.import_module("src.web.app")
    launch_id = "fresh-launch-id"
    monkeypatch.setattr(app_module, "_launch_readiness_id", launch_id)
    before = app_module._game_session.copy()

    response = app_module.app.test_client().get(
        P2P_READINESS_PATH,
        query_string={"launch_id": "request-echo-must-not-win"},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {"launch_id": launch_id, "pid": os.getpid()}
    assert "request-echo-must-not-win" not in response.get_data(as_text=True)
    assert app_module._game_session == before


def test_p2p_selection_mode_is_machine_readable(monkeypatch, capsys):
    server_module = importlib.import_module("scripts.run_p2p_server")
    monkeypatch.setattr(server_module, "select_port", lambda **kwargs: 61236)
    assert server_module.main(["--select-port", "--port", "61230"]) == 0
    assert capsys.readouterr().out.strip() == "61236"


def test_p2p_explicit_port_is_strict(monkeypatch):
    server_module = importlib.import_module("scripts.run_p2p_server")
    captured: dict = {}

    def fake_run_server(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(server_module, "run_server", fake_run_server)
    assert server_module.main(["--port", "61237"]) == 0
    assert captured == {
        "host": "127.0.0.1",
        "port": 61237,
        "debug": False,
        "strict_port": True,
        "launch_id": None,
    }


def test_p2p_consumes_inherited_launch_identity_and_passes_it_keyword_only(monkeypatch):
    server_module = importlib.import_module("scripts.run_p2p_server")
    captured: dict = {}
    monkeypatch.setenv(server_module.LAUNCH_ID_ENV, "fresh-launch-id")

    def fake_run_server(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(server_module, "run_server", fake_run_server)
    assert server_module.main(["--port", "61243"]) == 0
    assert captured["launch_id"] == "fresh-launch-id"
    assert server_module.LAUNCH_ID_ENV not in os.environ


def test_p2p_powershell_passes_selected_port_to_both_processes():
    script = open("scripts/start_p2p.ps1", encoding="utf-8").read()
    assert '"--select-port"' in script
    assert '"--port", [string]$Port' in script
    assert '"http://127.0.0.1:$Port"' in script
    assert '$LaunchId = [Guid]::NewGuid().ToString("N")' in script
    assert '$env:FIVE_D_P2P_LAUNCH_ID = $LaunchId' in script
    assert 'Remove-Item Env:FIVE_D_P2P_LAUNCH_ID' in script
    assert '"/__p2p/readiness"' in script
    assert '$httpHandler.UseProxy = $false' in script
    assert '$httpHandler.AllowAutoRedirect = $false' in script
    assert '-NoNewWindow' in script
    assert 'if ($server.HasExited)' in script
    assert 'if ($tunnel.HasExited)' in script
