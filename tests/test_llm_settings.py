"""Browser-configured credentials: local-only, atomic and never echoed."""
import json

import pytest

from src.ai import llm_client, llm_settings
from src.ai.llm_client import LLMRequestError
from src.web.app import app
from tests.test_llm_ai import isolated  # isolated file and environment fixture


def settings_payload(client, **changes):
    current = client.get("/api/ai/llm_status").get_json()
    return {"revision": current["revision"], "api_key": "testing-key-only",
            "base_url": "https://api.deepseek.com", "model": "deepseek-flash",
            "timeout_seconds": 8, "max_requests": 80, **changes}


def test_web_save_normalizes_and_never_echoes_or_calls_provider(monkeypatch):
    monkeypatch.setattr(llm_client, "request_completion", lambda *args: pytest.fail("save must not call provider"))
    client = app.test_client()
    payload = settings_payload(client, base_url=" api.deepseek.com/chat/completions/ ", api_key=" testing-key-only ")
    saved = client.post("/api/ai/llm_config", json=payload)
    assert saved.status_code == 200
    result = saved.get_json()
    assert result["ready"] and result["has_key"]
    assert result["base_url"] == "https://api.deepseek.com"
    assert "testing-key-only" not in saved.get_data(as_text=True) and "api_key" not in result
    assert llm_client.load_llm_config().api_key == "testing-key-only"
    assert "testing-key-only" not in client.get("/api/ai/llm_status").get_data(as_text=True)
    updated = client.post("/api/ai/llm_config", json=settings_payload(client, api_key="", max_requests=22))
    assert updated.status_code == 200 and updated.get_json()["max_requests"] == 22
    assert llm_client.load_llm_config().api_key == "testing-key-only"
    assert client.get("/api/ai/llm_status").headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("changes,fragment", [
    ({"api_key": ""}, "首次"), ({"api_key": "bad\nsecret"}, "密钥格式"),
    ({"api_key": "••••••"}, "密钥格式"), ({"api_key": "Bearer secret"}, "密钥格式"),
    ({"base_url": "http://example.com"}, "HTTPS"),
    ({"base_url": "https://example.com?api_key=never-echo-me"}, "接口地址"),
    ({"base_url": "https://user:password@example.com"}, "接口地址"),
    ({"model": ""}, "模型名称"), ({"max_requests": 201}, "请求上限"),
    ({"max_requests": True}, "请求上限"), ({"timeout_seconds": 16}, "等待"),
])
def test_invalid_form_never_writes_or_exposes_input(changes, fragment):
    client = app.test_client()
    response = client.post("/api/ai/llm_config", json=settings_payload(client, **changes))
    assert response.status_code == 400
    assert fragment in response.get_json()["error"]
    assert "never-echo-me" not in response.get_data(as_text=True)
    assert not llm_client.CONFIG_PATH.exists()


def test_switching_endpoint_requires_replacement_key_and_stale_form_conflicts():
    client = app.test_client()
    original = settings_payload(client)
    assert client.post("/api/ai/llm_config", json=original).status_code == 200
    before = llm_client.CONFIG_PATH.read_bytes()
    assert client.post("/api/ai/llm_config", json=original).status_code == 409
    response = client.post("/api/ai/llm_config", json=settings_payload(client, api_key="", base_url="https://other.example/v1"))
    assert response.status_code == 400 and "新密钥" in response.get_json()["error"]
    assert llm_client.CONFIG_PATH.read_bytes() == before
    assert client.post("/api/ai/llm_config", json=settings_payload(client, api_key="other-test-key", base_url="https://other.example/v1/chat/completions")).status_code == 200
    assert llm_client.load_llm_config().base_url == "https://other.example/v1"


def test_write_failure_preserves_original_and_cleans_temporary_file(monkeypatch):
    client = app.test_client()
    assert client.post("/api/ai/llm_config", json=settings_payload(client)).status_code == 200
    before = llm_client.CONFIG_PATH.read_bytes()
    def fail(*args):
        raise OSError("never-expose-private-details")
    monkeypatch.setattr(llm_settings.os, "replace", fail)
    response = client.post("/api/ai/llm_config", json=settings_payload(client, api_key="new-test-key"))
    assert response.status_code == 400 and "原有配置未被覆盖" in response.get_json()["error"]
    assert "private-details" not in response.get_data(as_text=True)
    assert llm_client.CONFIG_PATH.read_bytes() == before
    assert not list(llm_client.CONFIG_PATH.parent.glob(".llm-*.tmp"))


def test_environment_override_is_read_only(monkeypatch):
    client = app.test_client()
    payload = settings_payload(client)
    monkeypatch.setenv("FIVE_D_CHESS_LLM_API_KEY", "env-test-key")
    state = client.get("/api/ai/llm_status")
    assert state.get_json()["editing_locked"] and state.get_json()["ready"]
    assert "env-test-key" not in state.get_data(as_text=True)
    assert client.post("/api/ai/llm_config", json=payload).status_code == 409
    assert state.get_json()["config_source"] == "environment"
    assert client.post("/api/ai/llm_delete", json={"revision": "missing", "confirmed": True}).status_code == 409
    assert not llm_client.CONFIG_PATH.exists()


def test_corrupt_file_can_be_repaired_with_new_key():
    llm_client.CONFIG_PATH.write_text('{"api_key":"private-corrupt-data"', encoding="utf-8")
    client = app.test_client()
    state = client.get("/api/ai/llm_status")
    assert not state.get_json()["ready"]
    assert "private-corrupt-data" not in state.get_data(as_text=True)
    assert client.post("/api/ai/llm_config", json=settings_payload(client)).status_code == 200


@pytest.mark.parametrize("headers,remote", [
    ({"CF-Connecting-IP": "203.0.113.1"}, "127.0.0.1"),
    ({"Forwarded": "for=203.0.113.1"}, "127.0.0.1"),
    ({"Host": "public.trycloudflare.com"}, "127.0.0.1"),
    ({"Origin": "https://other.example"}, "127.0.0.1"),
    ({"Sec-Fetch-Site": "cross-site"}, "127.0.0.1"), ({}, "192.168.0.5"),
])
def test_remote_cannot_write_or_test(monkeypatch, headers, remote):
    monkeypatch.setattr(llm_client, "request_completion", lambda *args: pytest.fail("remote call"))
    client = app.test_client()
    data = settings_payload(client)
    kwargs = {"headers": headers, "environ_overrides": {"REMOTE_ADDR": remote}}
    assert client.post("/api/ai/llm_config", json=data, **kwargs).status_code == 403
    assert client.post("/api/ai/llm_test", json={"revision": "missing"}, **kwargs).status_code == 403
    assert client.post("/api/ai/llm_delete", json={"revision": "missing", "confirmed": True}, **kwargs).status_code == 403
    state = client.get("/api/ai/llm_status", **kwargs)
    assert state.status_code == 403 and "config_path" not in state.get_json()
    assert not llm_client.CONFIG_PATH.exists()


@pytest.mark.parametrize("outcome", ["ok", "timeout", "credentials", "bad_reply"])
def test_connection_button_calls_once_using_saved_config(monkeypatch, outcome):
    client = app.test_client()
    saved = client.post("/api/ai/llm_config", json=settings_payload(client)).get_json()
    calls = []
    def connect(config, messages):
        calls.append(config)
        assert "testing-key-only" not in json.dumps(messages)
        if outcome in ("timeout", "credentials"):
            raise LLMRequestError(outcome)
        return {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}' if outcome == "ok" else 'private-response-data'}}]}
    monkeypatch.setattr(llm_client, "request_completion", connect)
    response = client.post("/api/ai/llm_test", json={"revision": saved["revision"]})
    assert len(calls) == 1 and calls[0].api_key == "testing-key-only"
    assert response.status_code == (200 if outcome == "ok" else 400)
    assert "private-response-data" not in response.get_data(as_text=True)
    assert "testing-key-only" not in response.get_data(as_text=True)
    assert client.post("/api/ai/llm_test", json={"revision": "stale"}).status_code == 409
    assert len(calls) == 1


def test_non_json_or_oversized_config_is_rejected():
    client = app.test_client()
    assert client.post("/api/ai/llm_config", data="anything").status_code == 400
    assert client.post("/api/ai/llm_config", json=[]).status_code == 400
    assert client.post("/api/ai/llm_config", json=settings_payload(client, api_key="x" * 17000)).status_code == 400
    page = client.get("/")
    assert page.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]


def test_storage_location_and_confirmed_delete_never_expose_key_or_touch_saves(monkeypatch):
    monkeypatch.setattr(llm_client, "request_completion", lambda *args: pytest.fail("delete must not call provider"))
    client = app.test_client()
    empty = client.get("/api/ai/llm_status").get_json()
    assert empty["config_source"] == "none" and empty["file_exists"] is False
    assert empty["config_path"] == str(llm_client.CONFIG_PATH.absolute())
    assert empty["config_directory"] == str(llm_client.CONFIG_PATH.parent.absolute())
    saved = client.post("/api/ai/llm_config", json=settings_payload(client)).get_json()
    assert saved["config_source"] == "file" and saved["file_exists"]
    unrelated = llm_client.CONFIG_PATH.parent / "save-fixture.json"
    unrelated.write_text("test game archive", encoding="utf-8")
    response = client.post("/api/ai/llm_delete", json={"revision": saved["revision"], "confirmed": True})
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    result = response.get_json()
    assert not result["ready"] and not result["has_key"] and not result["file_exists"]
    assert result["revision"] == "missing" and result["config_source"] == "none"
    assert "testing-key-only" not in response.get_data(as_text=True)
    assert not llm_client.CONFIG_PATH.exists() and unrelated.read_text() == "test game archive"
    assert client.post("/api/ai/llm_test", json={"revision": "missing"}).status_code == 400
    assert client.post("/api/ai/llm_config", json=settings_payload(client, api_key="")).status_code == 400
    assert client.post("/api/ai/llm_delete", json={"revision": "missing", "confirmed": True}).status_code == 200


@pytest.mark.parametrize("extra", [{}, {"confirmed": False}, {"confirmed": 1}, {"confirmed": "true"}, {"confirmed": True, "path": "elsewhere"}])
def test_delete_requires_explicit_confirmation_and_fixed_target(extra):
    client = app.test_client()
    saved = client.post("/api/ai/llm_config", json=settings_payload(client)).get_json()
    before = llm_client.CONFIG_PATH.read_bytes()
    assert client.post("/api/ai/llm_delete", json={"revision": saved["revision"], **extra}).status_code == 400
    assert llm_client.CONFIG_PATH.read_bytes() == before


def test_stale_delete_cannot_remove_replaced_key_and_delete_failure_preserves_file(monkeypatch):
    client = app.test_client()
    old = client.post("/api/ai/llm_config", json=settings_payload(client)).get_json()
    current = client.post("/api/ai/llm_config", json=settings_payload(client, api_key="replacement-test-key")).get_json()
    assert client.post("/api/ai/llm_delete", json={"revision": old["revision"], "confirmed": True}).status_code == 409
    before = llm_client.CONFIG_PATH.read_bytes()
    def denied(*args, **kwargs):
        raise PermissionError("private-system-details")
    monkeypatch.setattr(type(llm_client.CONFIG_PATH), "unlink", denied)
    response = client.post("/api/ai/llm_delete", json={"revision": current["revision"], "confirmed": True})
    assert response.status_code == 400 and "配置仍保留" in response.get_json()["error"]
    assert "private-system-details" not in response.get_data(as_text=True)
    assert llm_client.CONFIG_PATH.read_bytes() == before


def test_corrupt_config_can_be_deleted_without_parsing_its_secret():
    llm_client.CONFIG_PATH.write_text('{"api_key":"private-corrupt-data"', encoding="utf-8")
    client = app.test_client()
    state = client.get("/api/ai/llm_status").get_json()
    assert state["file_exists"] and not state["ready"]
    result = client.post("/api/ai/llm_delete", json={"revision": state["revision"], "confirmed": True})
    assert result.status_code == 200 and not llm_client.CONFIG_PATH.exists()
    assert "private-corrupt-data" not in result.get_data(as_text=True)


def test_running_ai_reloads_replacement_and_stops_paid_requests_after_delete(monkeypatch):
    from src.ai import llm_ai
    from src.engine import FiveDEngine
    from tests.test_llm_ai import completion
    client = app.test_client()
    client.post("/api/ai/llm_config", json=settings_payload(client))
    engine = FiveDEngine()
    ai = llm_ai.LLMAI(engine.current_turn_color)
    calls = []
    def choose(config, messages):
        calls.append(config)
        return completion()
    monkeypatch.setattr(llm_ai, "request_completion", choose)
    ai.plan_action(engine)
    assert calls[-1].api_key == "testing-key-only"
    saved = client.post("/api/ai/llm_config", json=settings_payload(client, api_key="replacement-test-key", model="custom-model")).get_json()
    ai.plan_action(engine)
    assert calls[-1].api_key == "replacement-test-key" and calls[-1].model == "custom-model"
    assert ai.requests_used == 2
    client.post("/api/ai/llm_delete", json={"revision": saved["revision"], "confirmed": True})
    plan = ai.plan_action(engine)
    assert len(calls) == 2 and ai.requests_used == 2 and plan.moves
    assert "配置已删除或不可用" in plan.warning and ai.last_source == "local"
    assert ai.config.api_key == "disabled"
    client.post("/api/ai/llm_config", json=settings_payload(client, api_key="third-test-key"))
    ai.plan_action(engine)
    assert calls[-1].api_key == "third-test-key" and ai.requests_used == 3
