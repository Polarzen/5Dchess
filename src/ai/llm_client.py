"""Optional, bounded Chat Completions transport; credentials stay on the host."""
from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import json
import os
from pathlib import Path
import queue
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


CONFIG_PATH = Path(__file__).resolve().parents[2] / ".runtime" / "llm.json"
_NETWORK_SLOT = threading.BoundedSemaphore(1)
MAX_RESPONSE_BYTES = 65536


class LLMConfigError(ValueError):
    pass


class LLMRequestError(RuntimeError):
    """Only fixed, public reason codes may cross the transport boundary."""


@dataclass(frozen=True)
class LLMConfig:
    api_key: str = field(repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    timeout_seconds: float = 8.0
    max_requests: int = 80

    def __post_init__(self):
        try:
            parsed = urlsplit(self.base_url)
            local = parsed.hostname == "localhost"
            if not local:
                try:
                    local = ipaddress.ip_address(parsed.hostname or "").is_loopback
                except ValueError:
                    pass
            if (not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment
                    or (parsed.scheme != "https" and not (parsed.scheme == "http" and local))):
                raise ValueError()
            _ = parsed.port
            if not isinstance(self.api_key, str) or not self.api_key.strip() or any(c.isspace() for c in self.api_key):
                raise ValueError()
            if not isinstance(self.model, str) or not 1 <= len(self.model) <= 100 or not self.model.isascii() or any(c.isspace() for c in self.model):
                raise ValueError()
            if isinstance(self.timeout_seconds, bool) or not 1 <= self.timeout_seconds <= 15:
                raise ValueError()
            if type(self.max_requests) is not int or not 1 <= self.max_requests <= 200:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise LLMConfigError("在线 AI 配置无效，请检查模型、接口地址、密钥及请求限制。") from None


def load_llm_config(path: Path | None = None) -> LLMConfig:
    """Read one project-local JSON file; environment values take precedence."""
    config_path = CONFIG_PATH if path is None else path
    values = {}
    try:
        if config_path.exists():
            if config_path.stat().st_size > 16384:
                raise ValueError()
            values = json.loads(config_path.read_text(encoding="utf-8-sig"))
            if not isinstance(values, dict):
                raise ValueError()
        for name in ("api_key", "base_url", "model", "timeout_seconds", "max_requests"):
            value = os.environ.get("FIVE_D_CHESS_LLM_" + name.upper())
            if value is not None:
                values[name] = float(value) if name == "timeout_seconds" else int(value) if name == "max_requests" else value
        if not values.get("api_key"):
            raise LLMConfigError("尚未配置在线 AI：请在下方填写自己的 API 密钥并保存。")
        return LLMConfig(**values)
    except LLMConfigError:
        raise
    except (OSError, ValueError, TypeError):
        raise LLMConfigError("无法读取在线 AI 配置，请检查 .runtime/llm.json 的 JSON 格式。") from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the Authorization header to a redirect destination.
        return None


def _post_completion(config: LLMConfig, messages: list[dict]) -> dict:
    body = {"model": config.model, "messages": messages, "stream": False,
            "max_tokens": 96, "response_format": {"type": "json_object"}}
    if urlsplit(config.base_url).hostname == "api.deepseek.com":
        body["thinking"] = {"type": "disabled"}
    request = Request(config.base_url.rstrip("/") + "/chat/completions",
                      data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      headers={"Authorization": "Bearer " + config.api_key,
                               "Content-Type": "application/json"}, method="POST")
    deadline = time.monotonic() + config.timeout_seconds
    try:
        with build_opener(_NoRedirect()).open(request, timeout=config.timeout_seconds) as response:
            content = bytearray()
            # read1 returns after one buffered/socket read. Keep-alive blank
            # lines cannot indefinitely extend the total response deadline.
            while time.monotonic() < deadline:
                chunk = response.read1(min(4096, MAX_RESPONSE_BYTES + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise LLMRequestError("invalid_response")
            else:
                raise LLMRequestError("timeout")
            return json.loads(content)
    except HTTPError as exc:
        code = exc.code
        exc.close()
        raise LLMRequestError("credentials" if code in (401, 402, 403) else "rate_limit" if code == 429 else "network") from None
    except LLMRequestError:
        raise
    except Exception:
        # No upstream body, URL, request headers or key is logged or exposed.
        raise LLMRequestError("network") from None


def request_completion(config: LLMConfig, messages: list[dict]) -> dict:
    """Absolute caller deadline, even during DNS; at most one live worker.

    A late result can never mutate a chess engine. The bounded slot remains
    held until the network worker actually exits, preventing thread buildup.
    """
    if not _NETWORK_SLOT.acquire(blocking=False):
        raise LLMRequestError("busy")
    result = queue.Queue(maxsize=1)

    def worker():
        try:
            result.put((True, _post_completion(config, messages)))
        except LLMRequestError as exc:
            result.put((False, str(exc)))
        except Exception:
            result.put((False, "network"))
        finally:
            _NETWORK_SLOT.release()

    thread = threading.Thread(target=worker, name="chess-llm-request", daemon=True)
    try:
        thread.start()
    except Exception:
        _NETWORK_SLOT.release()
        raise LLMRequestError("network") from None
    try:
        success, payload = result.get(timeout=config.timeout_seconds)
    except queue.Empty:
        raise LLMRequestError("timeout") from None
    if not success:
        raise LLMRequestError(payload)
    return payload
