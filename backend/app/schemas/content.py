import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ScriptGenerateRequest(RequestModel):
    account_id: uuid.UUID
    topic: str = Field(min_length=1, max_length=500)
    strategy_type: Literal["ip", "brand"]
    duration: Literal["30s", "60s", "90s"] = "30s"
    style: str = Field(default="", max_length=100)
    local_cities: list[ShortText] | None = Field(default=None, max_length=20)
    count: int = Field(default=1, ge=1, le=5)


class CopywritingGenerateRequest(RequestModel):
    account_id: uuid.UUID
    topic: str = Field(min_length=1, max_length=500)
    strategy_type: Literal["ip", "brand"]
    platform: Literal["douyin", "xiaohongshu", "weixin_video"] = "douyin"
    count: int = Field(default=1, ge=1, le=5)


class LocalizeRequest(RequestModel):
    content_id: uuid.UUID | None = None
    content: str | None = Field(default=None, min_length=1, max_length=50_000)
    cities: list[ShortText] = Field(min_length=1, max_length=20)
    account_id: uuid.UUID | None = None
    strategy_type: Literal["ip", "brand"] | None = None

    @model_validator(mode="after")
    def require_content_source(self):
        if self.content_id is None and not self.content:
            raise ValueError("content_id 和 content 至少需要填写一项")
        return self


class ContentRiskRewriteRequest(RequestModel):
    max_attempts: int = Field(default=3, ge=1, le=3)
    platform: Literal["douyin", "xiaohongshu", "weixin_video", "channels"] | None = None


class ContentUpdate(RequestModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body_text: str | None = Field(default=None, min_length=1, max_length=50_000)
    tags: list[ShortText] | None = Field(default=None, max_length=50)
    status: (
        Literal[
            "draft",
            "ai_generated",
            "risk_checked",
            "risk_failed",
            "approved",
            "human_reviewed",
            "scheduled",
            "published",
            "stats_synced",
        ]
        | None
    ) = None


class ContentOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    content_type: str
    strategy_type: str
    title: str
    body_text: str
    tags: list | None = None
    media_urls: list | None = None
    status: str
    risk_check_result: dict | None = None
    knowledge_references: list[dict] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
