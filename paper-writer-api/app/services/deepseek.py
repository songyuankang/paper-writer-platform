"""DeepSeek API 客户端（OpenAI 兼容接口）。

支持 deepseek-chat / deepseek-reasoner，提供普通与流式调用；
统一错误映射：鉴权失败、余额不足、限流、超时、服务端错误。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Iterator

DEFAULT_TIMEOUT = 300
_ACTIVE: dict | None = None


class DeepSeekError(Exception):
    """DeepSeek 调用基类错误。"""


class DeepSeekConfigError(DeepSeekError):
    """未配置 API Key 等配置错误。"""


class DeepSeekAuthError(DeepSeekError):
    """API Key 无效（401）。"""


class DeepSeekBalanceError(DeepSeekError):
    """余额不足（402）。"""


class DeepSeekRateLimitError(DeepSeekError):
    """请求过于频繁（429）。"""


class DeepSeekModelError(DeepSeekError):
    """请求参数/模型错误（400）。"""


class DeepSeekTimeoutError(DeepSeekError):
    """超时或网络错误。"""


class DeepSeekServerError(DeepSeekError):
    """服务端错误（5xx）。"""


class connection:
    """上下文管理器：进入时从统一模型对象设置连接，退出时恢复。"""

    def __init__(self, cfg):
        self.target = {
            "base_url": cfg.base_url,
            "api_key": cfg.api_key,
            "model": cfg.model,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
        }
        self.previous = _ACTIVE

    def __enter__(self):
        global _ACTIVE
        _ACTIVE = self.target
        return self

    def __exit__(self, *exc):
        global _ACTIVE
        _ACTIVE = self.previous
        return False


def _current() -> dict:
    if not _ACTIVE:
        raise DeepSeekConfigError("未配置 AI 模型")
    return _ACTIVE


def is_enabled() -> bool:
    return _ACTIVE is not None


def _error_message(body: str) -> str:
    try:
        data = json.loads(body)
        return str(data.get("error", {}).get("message") or data.get("message") or body)[:300]
    except Exception:  # noqa: BLE001
        return body[:300]


def _post(base_url: str, api_key: str, payload: dict, timeout: int) -> dict:
    url = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        message = _error_message(body)
        if exc.code == 401:
            raise DeepSeekAuthError(f"DeepSeek API Key 无效（401）：{message}")
        if exc.code == 402:
            raise DeepSeekBalanceError(f"DeepSeek 余额不足（402）：{message}")
        if exc.code == 429:
            raise DeepSeekRateLimitError(f"DeepSeek 请求过于频繁（429）：{message}")
        if exc.code == 400:
            raise DeepSeekModelError(f"DeepSeek 请求参数/模型错误（400）：{message}")
        raise DeepSeekServerError(f"DeepSeek 服务错误（{exc.code}）：{message}")
    except urllib.error.URLError as exc:
        raise DeepSeekTimeoutError(f"DeepSeek 请求失败或超时：{exc.reason}")
    except (TimeoutError, OSError) as exc:
        # Python 3.10+ 的 socket 读取/连接超时会直接抛 TimeoutError（OSError 子类），
        # 而不是 URLError，需要单独映射，避免原始异常冒泡成 500。
        raise DeepSeekTimeoutError(f"DeepSeek 请求超时或网络错误：{exc}")


def chat_with(base_url: str, api_key: str, model: str,
              messages: list[dict], *, temperature: float = 0.7,
              max_tokens: int = 4000, timeout: int | None = None,
              retries: int = 1) -> str:
    """通用 OpenAI 兼容非流式对话。对限流/超时/5xx 做一次重试。"""
    if not (api_key or "").strip():
        raise DeepSeekConfigError("未配置 DEEPSEEK_API_KEY")
    if not (base_url or "").strip():
        raise DeepSeekConfigError("未配置 DEEPSEEK_BASE_URL")
    if not (model or "").strip():
        raise DeepSeekConfigError("未配置 DEEPSEEK_MODEL")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    timeout = timeout or DEFAULT_TIMEOUT
    last_error: DeepSeekError | None = None
    for attempt in range(retries + 1):
        try:
            data = _post(base_url, api_key, payload, timeout)
            return (data["choices"][0]["message"]["content"] or "").strip()
        except (DeepSeekTimeoutError, DeepSeekServerError,
                DeepSeekRateLimitError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
        except DeepSeekError:
            raise
    if last_error is not None:
        raise last_error
    raise DeepSeekServerError("DeepSeek 调用失败")


def chat(messages: list[dict], *, max_tokens: int | None = None) -> str:
    """使用当前统一模型连接的非流式对话。

    :param max_tokens: 覆盖模型配置的 token 上限；不传时使用模型配置值。
    """
    cfg = _current()
    return chat_with(
        cfg["base_url"], cfg["api_key"], cfg["model"], messages,
        temperature=cfg["temperature"],
        max_tokens=max_tokens or cfg["max_tokens"])


def chat_stream_with(base_url: str, api_key: str, model: str,
                     messages: list[dict], *, temperature: float = 0.7,
                     max_tokens: int = 4000,
                     timeout: int | None = None) -> Iterator[str]:
    """通用 OpenAI 兼容流式对话，逐段产出增量文本（SSE）。"""
    if not (api_key or "").strip():
        raise DeepSeekConfigError("未配置 DEEPSEEK_API_KEY")
    if not (base_url or "").strip():
        raise DeepSeekConfigError("未配置 DEEPSEEK_BASE_URL")
    if not (model or "").strip():
        raise DeepSeekConfigError("未配置 DEEPSEEK_MODEL")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or DEFAULT_TIMEOUT) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                if delta:
                    yield delta
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        message = _error_message(body)
        if exc.code == 429:
            raise DeepSeekRateLimitError(f"DeepSeek 请求过于频繁（429）：{message}")
        if exc.code == 401:
            raise DeepSeekAuthError(f"DeepSeek API Key 无效（401）：{message}")
        if exc.code == 402:
            raise DeepSeekBalanceError(f"DeepSeek 余额不足（402）：{message}")
        raise DeepSeekServerError(f"DeepSeek 服务错误（{exc.code}）：{message}")
    except urllib.error.URLError as exc:
        raise DeepSeekTimeoutError(f"DeepSeek 请求失败或超时：{exc.reason}")
    except (TimeoutError, OSError) as exc:
        # Python 3.10+ 的 socket 读取/连接超时会直接抛 TimeoutError（OSError 子类），
        # 而不是 URLError，需要单独映射，避免原始异常冒泡成 500。
        raise DeepSeekTimeoutError(f"DeepSeek 请求超时或网络错误：{exc}")


def chat_stream(messages: list[dict]) -> Iterator[str]:
    """使用当前统一模型连接的流式对话。"""
    cfg = _current()
    return chat_stream_with(
        cfg["base_url"], cfg["api_key"], cfg["model"], messages,
        temperature=cfg["temperature"], max_tokens=cfg["max_tokens"])
