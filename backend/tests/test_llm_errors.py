import json
import socket

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response

from app.core.exceptions import register_exception_handlers
from app.services.llm_client import (
    LLMClient,
    LLMConfigurationError,
    LLMRuntimeConfig,
    ensure_safe_llm_base_url,
    settings,
)
from app.services import llm_client


@pytest.mark.asyncio
async def test_missing_llm_key_is_a_configuration_error(monkeypatch):
    monkeypatch.setattr(settings, "AI_MOCK_MODE", False)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")

    with pytest.raises(LLMConfigurationError, match="模型配置"):
        await LLMClient().generate(prompt="test")


@pytest.mark.asyncio
async def test_llm_configuration_error_returns_readable_503():
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/generate")
    async def generate():
        raise LLMConfigurationError("AI 模型未配置：请填写 DEEPSEEK_API_KEY。")

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/generate")

    assert response.status_code == 503
    assert response.json()["message"] == "AI 模型未配置：请填写 DEEPSEEK_API_KEY。"


@pytest.mark.asyncio
async def test_chat_completions_protocol(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ALLOW_PRIVATE_BASE_URL", True)

    async def handler(request: Request) -> Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret-key"
        return Response(200, json={"choices": [{"message": {"content": "chat-ok"}}]})

    config = LLMRuntimeConfig(
        provider_name="Test Chat",
        protocol="chat_completions",
        base_url="https://llm.example/v1",
        model="test-model",
        api_key="secret-key",
        timeout_seconds=30,
    )
    result = await LLMClient(
        runtime_override=config, transport=MockTransport(handler)
    ).generate(prompt="hello")
    assert result == ["chat-ok"]


@pytest.mark.asyncio
async def test_volcengine_coding_disables_thinking(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ALLOW_PRIVATE_BASE_URL", True)

    async def handler(request: Request) -> Response:
        payload = json.loads(request.content)
        assert request.url.path == "/api/coding/v3/chat/completions"
        assert payload["thinking"] == {"type": "disabled"}
        return Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    config = LLMRuntimeConfig(
        provider_name="Volcengine Ark GLM2",
        protocol="chat_completions",
        base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        model="glm-5-2",
        api_key="secret-key",
        timeout_seconds=30,
    )
    result = await LLMClient(
        runtime_override=config, transport=MockTransport(handler)
    ).generate(prompt="hello")
    assert result == ["OK"]


@pytest.mark.asyncio
async def test_responses_protocol(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ALLOW_PRIVATE_BASE_URL", True)

    async def handler(request: Request) -> Response:
        assert request.url.path == "/v1/responses"
        return Response(
            200,
            json={
                "output": [
                    {"content": [{"type": "output_text", "text": "responses-ok"}]}
                ]
            },
        )

    config = LLMRuntimeConfig(
        provider_name="Test Responses",
        protocol="responses",
        base_url="https://llm.example/v1",
        model="test-model",
        api_key="secret-key",
        timeout_seconds=30,
    )
    result = await LLMClient(
        runtime_override=config, transport=MockTransport(handler)
    ).generate(prompt="hello")
    assert result == ["responses-ok"]


@pytest.mark.asyncio
async def test_private_llm_endpoint_is_blocked(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ALLOW_PRIVATE_BASE_URL", False)
    with pytest.raises(LLMConfigurationError, match="本机或内网"):
        await ensure_safe_llm_base_url("http://127.0.0.1:8000/v1")


@pytest.mark.asyncio
async def test_fake_ip_dns_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ALLOW_PRIVATE_BASE_URL", False)
    monkeypatch.setattr(settings, "LLM_ALLOW_FAKE_IP_DNS", False)
    monkeypatch.setattr(
        llm_client.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.45", 443))
        ],
    )
    with pytest.raises(LLMConfigurationError, match="本机或内网"):
        await ensure_safe_llm_base_url("https://llm.example/v1")


@pytest.mark.asyncio
async def test_fake_ip_dns_can_be_enabled_without_allowing_literal_ip(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ALLOW_PRIVATE_BASE_URL", False)
    monkeypatch.setattr(settings, "LLM_ALLOW_FAKE_IP_DNS", True)
    monkeypatch.setattr(
        llm_client.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.45", 443))
        ],
    )

    await ensure_safe_llm_base_url("https://llm.example/v1")
    with pytest.raises(LLMConfigurationError, match="本机或内网"):
        await ensure_safe_llm_base_url("https://198.18.0.45/v1")
