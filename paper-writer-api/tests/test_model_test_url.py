import socket

import pytest

from app.models.model_config import ModelTestRequest
from app.services import deepseek, model_service


def _payload(base_url: str) -> ModelTestRequest:
    return ModelTestRequest(
        base_url=base_url,
        api_key="test-key",
        model="test-model",
    )


def _must_not_call_model(**_kwargs):
    raise AssertionError("SSRF URL must be rejected before any model request")


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://example.com/v1",
        "http://localhost:8000/v1",
        "http://127.0.0.1:8000/v1",
        "http://[::1]:8000/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://192.168.1.10/v1",
        "http://user:password@example.com/v1",
    ],
)
def test_connection_rejects_non_public_or_malformed_urls_before_request(
    monkeypatch,
    base_url,
):
    monkeypatch.setattr(deepseek, "chat_with", _must_not_call_model)

    with pytest.raises(ValueError):
        model_service.test_connection(_payload(base_url))


def test_connection_rejects_hostname_resolving_to_private_address(monkeypatch):
    monkeypatch.setattr(
        model_service.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))
        ],
    )
    monkeypatch.setattr(deepseek, "chat_with", _must_not_call_model)

    with pytest.raises(ValueError, match="内网"):
        model_service.test_connection(_payload("https://internal.example/v1"))


def test_connection_allows_public_agnes_style_url_without_network_call(monkeypatch):
    calls: dict[str, object] = {}
    monkeypatch.setattr(
        model_service.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        ],
    )

    def fake_chat_with(**kwargs):
        calls.update(kwargs)
        return "pong"

    monkeypatch.setattr(deepseek, "chat_with", fake_chat_with)
    base_url = "https://apihub.agnes-ai.com/v1"

    result = model_service.test_connection(_payload(base_url))

    assert result["ok"] is True
    assert calls["base_url"] == base_url


def test_saved_model_test_url_uses_the_same_ssrf_guard(monkeypatch):
    monkeypatch.setattr(
        model_service,
        "get_model",
        lambda _model_id: {
            "base_url": "http://127.0.0.1:8000/v1",
            "api_key": "test-key",
            "model": "test-model",
        },
    )
    monkeypatch.setattr(deepseek, "chat_with", _must_not_call_model)

    with pytest.raises(ValueError, match="内网"):
        model_service.test_connection(ModelTestRequest(id="saved-model"))
