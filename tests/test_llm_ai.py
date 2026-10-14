"""Online AI safety/turn semantics; no real keys or paid API calls."""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

import pytest

from src.ai import apply_action_plan, engine_state_signature
from src.ai.action_planner import ActionPlanner, ActionSearchBudget, ActionSearchResult
from src.ai import llm_ai, llm_client
from src.ai.llm_ai import LLMAI, build_messages
from src.ai.llm_client import LLMConfig, LLMConfigError, LLMRequestError, load_llm_config
from src.engine import FiveDEngine
from src.utils.constants import ChessColor
from src.web.app import app, _game_session
from tests.test_ai_action_planning import _two_required_boards_engine, _branching_engine


CONFIG = LLMConfig(api_key="test-only-not-a-secret")


def completion(index=1):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"candidate_id": index})}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 8}}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for name in ("API_KEY", "BASE_URL", "MODEL", "TIMEOUT_SECONDS", "MAX_REQUESTS"):
        monkeypatch.delenv("FIVE_D_CHESS_LLM_" + name, raising=False)
    monkeypatch.setattr(llm_client, "CONFIG_PATH", tmp_path / "llm.json")
    before = dict(_game_session)
    yield
    _game_session.clear()
    _game_session.update(before)


def test_config_is_relative_safe_and_environment_overrides(monkeypatch, tmp_path):
    path = tmp_path / "llm.json"
    with pytest.raises(LLMConfigError, match="尚未配置"):
        load_llm_config(path)
    path.write_text(json.dumps({"api_key": CONFIG.api_key}), encoding="utf-8-sig")
    monkeypatch.setenv("FIVE_D_CHESS_LLM_MODEL", "another-model")
    monkeypatch.setenv("FIVE_D_CHESS_LLM_MAX_REQUESTS", "9")
    config = load_llm_config(path)
    assert config.model == "another-model" and config.max_requests == 9
    assert CONFIG.api_key not in repr(config)
    path.write_text('{"api_key":"private-value", broken', encoding="utf-8")
    with pytest.raises(LLMConfigError) as exc:
        load_llm_config(path)
    assert "private-value" not in str(exc.value)


@pytest.mark.parametrize("change", [
    {"base_url": "http://example.com"}, {"base_url": "https://user:pass@example.com"},
    {"base_url": "https://example.com?key=value"}, {"api_key": "bad\nheader"},
    {"timeout_seconds": 0}, {"timeout_seconds": 16}, {"max_requests": True},
    {"max_requests": 201}, {"model": ""}, {"model": "x\nsecret"},
])
def test_invalid_config_is_rejected_without_values(change):
    with pytest.raises(LLMConfigError):
        replace(CONFIG, **change)


@pytest.mark.parametrize("factory", [FiveDEngine, _two_required_boards_engine, _branching_engine])
def test_llm_selects_complete_action_without_mutating_snapshot(monkeypatch, factory):
    engine = factory()
    before = engine_state_signature(engine)
    calls = []
    def select(config, messages):
        calls.append(json.loads(messages[1]["content"]))
        assert CONFIG.api_key not in json.dumps(messages)
        return completion(1)
    monkeypatch.setattr(llm_ai, "request_completion", select)
    ai = LLMAI(engine.current_turn_color, CONFIG)
    plan = ai.plan_action(engine)
    assert engine_state_signature(engine) == before
    assert len(calls) == 1 and ai.last_source == "llm"
    assert plan.metadata["selected_index"] == 1
    assert ai.prompt_tokens == 500 and ai.completion_tokens == 8
    apply_action_plan(engine, plan)
    assert engine.current_turn_color == ChessColor.BLACK
    assert len(engine.action_history) == 1
    assert engine.current_action is None or not engine.current_action.moves


@pytest.mark.parametrize("reply", [
    completion(-1), completion(999), completion(True), completion("1"),
    {"choices": []}, {"choices": [{"finish_reason": "length", "message": {"content": '{}'}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": 'not json'}}]},
])
def test_invalid_choice_falls_back_to_legal_action(monkeypatch, reply):
    monkeypatch.setattr(llm_ai, "request_completion", lambda *args: reply)
    engine = FiveDEngine()
    ai = LLMAI(ChessColor.WHITE, CONFIG)
    plan = ai.plan_action(engine)
    assert plan.warning and ai.last_source == "local"
    apply_action_plan(engine, plan)
    assert engine.current_turn_color == ChessColor.BLACK


def test_request_limit_and_network_failure_do_not_retry(monkeypatch):
    calls = []
    def fail(*args):
        calls.append(1)
        raise LLMRequestError("timeout")
    monkeypatch.setattr(llm_ai, "request_completion", fail)
    ai = LLMAI(ChessColor.WHITE, replace(CONFIG, max_requests=1))
    engine = FiveDEngine()
    assert "超时" in ai.plan_action(engine).warning
    assert "上限" in ai.plan_action(engine).warning
    assert len(calls) == 1


def test_only_candidate_skips_network_and_repetition_preference(monkeypatch):
    engine = FiveDEngine()
    candidates = ActionPlanner(ActionSearchBudget(max_actions=2)).search(engine).candidates
    monkeypatch.setattr(ActionPlanner, "search", lambda *args: ActionSearchResult(candidates, 2, frontier_repetitions=(2, 0)))
    monkeypatch.setattr(llm_ai, "request_completion", lambda *args: pytest.fail("unnecessary paid request"))
    ai = LLMAI(ChessColor.WHITE, CONFIG)
    assert ai.plan_action(engine).moves == candidates[1]
    assert ai.requests_used == 0


def test_context_cap_skips_network(monkeypatch):
    monkeypatch.setattr(llm_ai, "build_messages", lambda *args: (_ for _ in ()).throw(LLMRequestError("context_limit")))
    monkeypatch.setattr(llm_ai, "request_completion", lambda *args: pytest.fail("oversized payload"))
    ai = LLMAI(ChessColor.WHITE, CONFIG)
    assert "上下文" in ai.plan_action(FiveDEngine()).warning
    assert ai.requests_used == 0


def test_deadline_and_single_worker_ignore_late_results(monkeypatch):
    release = threading.Event()
    finished = threading.Event()
    def slow(*args):
        release.wait(4)
        finished.set()
        return completion()
    monkeypatch.setattr(llm_client, "_post_completion", slow)
    started = time.monotonic()
    try:
        with pytest.raises(LLMRequestError, match="timeout"):
            llm_client.request_completion(replace(CONFIG, timeout_seconds=1), [])
        assert time.monotonic() - started < 2
        with pytest.raises(LLMRequestError, match="busy"):
            llm_client.request_completion(CONFIG, [])
    finally:
        release.set()
        assert finished.wait(2)
    # Wait for the worker's finally, not just its transport return.
    assert llm_client._NETWORK_SLOT.acquire(timeout=2)
    llm_client._NETWORK_SLOT.release()


@pytest.mark.parametrize("status", [200, 401, 429, 302])
def test_real_http_transport_and_redirect_does_not_forward_key(status):
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            received.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "/redirect-target")
            self.end_headers()
            self.wfile.write(json.dumps(completion()).encode())
        do_GET = do_POST
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = replace(CONFIG, base_url=f"http://127.0.0.1:{server.server_port}/v1")
        if status == 200:
            assert llm_client.request_completion(config, []) == completion()
        else:
            with pytest.raises(LLMRequestError):
                llm_client.request_completion(config, [])
        assert len(received) == 1
        path, auth, body = received[0]
        assert path == "/v1/chat/completions" and auth == "Bearer " + CONFIG.api_key
        assert body["max_tokens"] == 96 and body["stream"] is False
        assert body["response_format"] == {"type": "json_object"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_web_config_missing_no_call_then_complete_turn(monkeypatch):
    client = app.test_client()
    assert client.get("/api/ai/llm_status").get_json()["ready"] is False
    started = client.post("/api/game/start", json={"mode": "pve", "difficulty": "llm"})
    assert started.status_code == 400
    monkeypatch.setenv("FIVE_D_CHESS_LLM_API_KEY", CONFIG.api_key)
    calls = []
    monkeypatch.setattr(llm_ai, "request_completion", lambda *args: (calls.append(1), completion())[1])
    ready = client.get("/api/ai/llm_status")
    assert ready.get_json()["ready"] is True and not calls
    assert CONFIG.api_key not in ready.get_data(as_text=True)
    state = client.post("/api/game/start", json={"mode": "pve", "difficulty": "llm", "player_color": "black"})
    assert state.status_code == 200 and not calls
    response = client.post("/api/game/ai_move", json={})
    assert response.status_code == 200
    assert response.get_json()["turn"] == "black" and len(calls) == 1
    assert response.get_json()["ai_opponent"]["last_source"] == "llm"
    assert CONFIG.api_key not in response.get_data(as_text=True)
    assert client.post("/api/game/ai_move", json={}).status_code == 409
    assert len(calls) == 1


@pytest.mark.parametrize("headers,remote", [
    ({"CF-Connecting-IP": "203.0.113.1"}, "127.0.0.1"),
    ({"X-Forwarded-For": "203.0.113.1"}, "127.0.0.1"),
    ({"Host": "public.trycloudflare.com"}, "127.0.0.1"),
    ({"Origin": "https://other.example"}, "127.0.0.1"),
    ({"Sec-Fetch-Site": "cross-site"}, "127.0.0.1"),
    ({}, "192.168.0.5"),
])
def test_public_visitors_cannot_spend_host_key(monkeypatch, headers, remote):
    monkeypatch.setenv("FIVE_D_CHESS_LLM_API_KEY", CONFIG.api_key)
    monkeypatch.setattr(llm_ai, "request_completion", lambda *args: pytest.fail("remote paid request"))
    client = app.test_client()
    client.post("/api/game/start", json={"mode": "pve", "difficulty": "llm", "player_color": "black"})
    kwargs = {"headers": headers, "environ_overrides": {"REMOTE_ADDR": remote}}
    assert client.get("/api/ai/llm_status", **kwargs).status_code == 403
    assert client.post("/api/game/start", json={"mode": "pve", "difficulty": "llm"}, **kwargs).status_code == 403
    assert client.post("/api/game/ai_move", json={}, **kwargs).status_code == 403
