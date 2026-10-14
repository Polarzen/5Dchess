"""Host-only settings storage. Public snapshots never contain credentials."""
from dataclasses import asdict
import json
import os
import tempfile
import threading
from urllib.parse import urlsplit, urlunsplit

from src.ai import llm_client
from src.ai.llm_client import LLMConfig, LLMConfigError, load_llm_config


_SETTINGS_LOCK = threading.RLock()
_FIELDS = ("api_key", "base_url", "model", "timeout_seconds", "max_requests")


class LLMSettingsConflict(LLMConfigError):
    pass


def _revision():
    try:
        stat = llm_client.CONFIG_PATH.stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"
    except FileNotFoundError:
        return "missing"
    except OSError:
        raise LLMConfigError("无法访问本机配置文件，请检查项目文件夹的写入权限。") from None


def _environment_locked():
    return any("FIVE_D_CHESS_LLM_" + name.upper() in os.environ for name in _FIELDS)


def public_llm_settings():
    with _SETTINGS_LOCK:
        result = {"ready": False, "has_key": False, "base_url": "https://api.deepseek.com",
                  "model": "deepseek-flash", "timeout_seconds": 8, "max_requests": 80,
                  "revision": _revision(), "editing_locked": _environment_locked()}
        try:
            config = load_llm_config()
        except LLMConfigError as exc:
            result["message"] = str(exc)
        else:
            result.update({name: getattr(config, name) for name in _FIELDS if name != "api_key"})
            result.update(ready=True, has_key=True)
        if result["editing_locked"]:
            result["message"] = "当前使用环境变量配置，网页只读。请在启动环境中修改，或移除覆盖项并重启后再使用网页设置。"
        return result


def normalize_base_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise LLMConfigError("请填写服务商接口地址。")
    value = value.strip()
    if any(c.isspace() for c in value):
        raise LLMConfigError("接口地址不能包含空格或换行。")
    if "://" not in value:
        value = "https://" + value
    try:
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError()
        path = parsed.path.rstrip("/")
        if path.endswith("/chat/completions"):
            path = path[:-len("/chat/completions")]
        normalized = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))
        LLMConfig(api_key="validation-placeholder", base_url=normalized)
        return normalized
    except (ValueError, TypeError):
        raise LLMConfigError("接口地址无效：公网地址需使用 HTTPS，不能包含密钥、查询参数或片段；本机模型可用回环 HTTP 地址。") from None


def save_llm_settings(data):
    if not isinstance(data, dict) or set(data) != set(_FIELDS) | {"revision"}:
        raise LLMConfigError("配置字段不完整，请重新打开设置后再保存。")
    with _SETTINGS_LOCK:
        if _environment_locked():
            raise LLMSettingsConflict("当前使用环境变量配置，网页不能覆盖。请移除环境变量覆盖并重启后再保存。")
        if data["revision"] != _revision():
            raise LLMSettingsConflict("配置已在其他窗口修改，请重新载入后再保存。")
        base_url = normalize_base_url(data["base_url"])
        key = data["api_key"]
        model = data["model"]
        if not isinstance(key, str) or len(key) > 4096:
            raise LLMConfigError("密钥格式不正确，请粘贴密钥本身。")
        key = key.strip()
        if not key:
            try:
                previous = load_llm_config()
            except LLMConfigError:
                raise LLMConfigError("首次配置需要填写 API 密钥。") from None
            if normalize_base_url(previous.base_url) != base_url:
                raise LLMConfigError("切换接口地址时，请填写对应的新密钥，避免把旧密钥发送给其他服务商。")
            key = previous.api_key
        if (not key.isascii() or any(c.isspace() or ord(c) < 33 for c in key)
                or key.lower().startswith("bearer") or set(key) <= {"*", "."}):
            raise LLMConfigError("密钥格式不正确：请粘贴密钥本身，不要包含遮罩、空格、换行或认证前缀。")
        if not isinstance(model, str) or not model.strip():
            raise LLMConfigError("请填写模型名称；选择 DeepSeek 可自动填写默认模型。")
        if type(data["timeout_seconds"]) not in (int, float) or not 1 <= data["timeout_seconds"] <= 15:
            raise LLMConfigError("网络等待时间须为 1 到 15 秒。")
        if type(data["max_requests"]) is not int or not 1 <= data["max_requests"] <= 200:
            raise LLMConfigError("每局请求上限须为 1 到 200 的整数。")
        config = LLMConfig(api_key=key, base_url=base_url, model=model.strip(),
                           timeout_seconds=data["timeout_seconds"], max_requests=data["max_requests"])
        temporary = None
        try:
            llm_client.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=llm_client.CONFIG_PATH.parent,
                                             prefix=".llm-", suffix=".tmp", delete=False) as stream:
                temporary = stream.name
                json.dump(asdict(config), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, llm_client.CONFIG_PATH)
        except OSError:
            raise LLMConfigError("保存失败，请检查项目目录是否可写；原有配置未被覆盖。") from None
        finally:
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
        result = public_llm_settings()
        result["message"] = "已保存到房主本机。尚未测试接口；新对局使用新配置，当前对局保持原配置。"
        return result


def test_llm_connection(revision):
    with _SETTINGS_LOCK:
        if revision != _revision():
            raise LLMSettingsConflict("配置已改变，请重新载入后再测试。")
        config = load_llm_config()
    response = llm_client.request_completion(config, [
        {"role": "system", "content": 'Connection check. Return only JSON: {"ok":true}.'},
        {"role": "user", "content": 'Return {"ok":true}.'},
    ])
    try:
        choice = response["choices"][0]
        if choice["finish_reason"] != "stop" or json.loads(choice["message"]["content"]).get("ok") is not True:
            raise ValueError()
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, RecursionError):
        raise llm_client.LLMRequestError("invalid_response") from None
    return {"success": True, "message": "连接测试通过：认证、模型与结构化回复可用。测试产生一次接口用量，不代表棋力或后续连接稳定性。"}
