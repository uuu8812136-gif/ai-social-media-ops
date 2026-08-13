from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LLMConfigPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider_name: str = Field(default="自定义模型", min_length=1, max_length=100)
    protocol: Literal["chat_completions", "responses"] = "chat_completions"
    base_url: str = Field(min_length=8, max_length=1000)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=4096)
    timeout_seconds: int = Field(default=120, ge=5, le=300)

    @field_validator("provider_name", "model")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("必须是有效的 http/https API 地址")
        if parsed.username or parsed.password:
            raise ValueError("地址中不能包含用户名或密码")
        if parsed.query or parsed.fragment:
            raise ValueError("地址中不能包含查询参数或锚点")
        return value


class LLMConfigView(BaseModel):
    source: Literal["database", "environment"]
    provider_name: str
    protocol: Literal["chat_completions", "responses"]
    base_url: str
    model: str
    api_key_configured: bool
    api_key_hint: str | None = None
    timeout_seconds: int
    updated_at: str | None = None


class LLMTestResult(BaseModel):
    ok: bool
    provider_name: str
    model: str
    protocol: str
    latency_ms: int
    preview: str
