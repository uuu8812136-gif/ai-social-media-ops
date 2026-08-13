import uuid
import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, field_validator


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AccountCreate(BaseModel):
    platform: str
    account_type: str
    account_name: str
    platform_id: str | None = None
    avatar_url: str | None = None
    strategy_engine: str
    owner_id: uuid.UUID | None = None


class AccountUpdate(BaseModel):
    account_name: str | None = None
    platform: str | None = None
    account_type: str | None = None
    platform_id: str | None = None
    avatar_url: str | None = None
    strategy_engine: str | None = None
    status: str | None = None
    owner_id: uuid.UUID | None = None


class AccountOut(BaseModel):
    id: uuid.UUID
    platform: str
    account_type: str
    account_name: str
    strategy_engine: str
    status: str
    owner_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CalendarCreate(BaseModel):
    account_id: uuid.UUID
    content_id: uuid.UUID | None = None
    scheduled_date: date
    scheduled_time: time | None = None


class CalendarUpdate(BaseModel):
    content_id: uuid.UUID | None = None
    scheduled_date: date | None = None
    scheduled_time: time | None = None
    publish_status: Literal["pending", "published", "skipped", "failed"] | None = None


class CalendarOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    content_id: uuid.UUID | None = None
    scheduled_date: date
    scheduled_time: time | None = None
    publish_status: str
    remind_sent: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AssetCreate(BaseModel):
    asset_type: Literal["image", "video", "document"]
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    file_url: str = Field(min_length=1, max_length=2048)
    file_size: int | None = Field(default=None, ge=0)
    thumbnail_url: str | None = Field(default=None, max_length=2048)
    tags: list[str] | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)
    is_public: bool = False

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        return AssetUpdate.validate_tags(value)


class AssetUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)
    is_public: bool | None = None

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [tag.strip() for tag in value]
        if any(not tag or len(tag) > 50 for tag in normalized):
            raise ValueError("标签不能为空且单个标签最多 50 个字符")
        return list(dict.fromkeys(normalized))


class AssetOut(BaseModel):
    id: uuid.UUID
    asset_type: str
    title: str
    description: str | None = None
    file_url: str
    preview_url: str | None = None
    file_size: int | None = None
    thumbnail_url: str | None = None
    tags: list | None = None
    category: str | None = None
    is_public: bool
    download_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadCreate(BaseModel):
    pool_type: Literal["consumer", "franchise", "local"]
    source_account_id: uuid.UUID | None = None
    source_platform: str | None = Field(default=None, max_length=20)
    customer_name: str = Field(min_length=1, max_length=100)
    customer_phone: str = Field(pattern=r"^\+?[0-9 -]{7,20}$")
    city_id: uuid.UUID | None = None
    requirement: str | None = Field(default=None, max_length=2000)
    house_info: dict | None = None


class LeadUpdate(BaseModel):
    customer_name: str | None = Field(default=None, min_length=1, max_length=100)
    requirement: str | None = Field(default=None, max_length=2000)
    status: (
        Literal[
            "pending",
            "assigned",
            "contacted",
            "appointment_measured",
            "measured",
            "quoted",
            "signed",
            "lost",
        ]
        | None
    ) = None
    signed_amount: Decimal | None = Field(default=None, ge=0)
    lost_reason: str | None = Field(default=None, max_length=1000)


class LeadAssign(BaseModel):
    dealer_id: uuid.UUID


class FollowupCreate(BaseModel):
    action: Literal[
        "contacted", "appointment_measured", "measured", "quoted", "signed", "lost"
    ]
    note: str | None = Field(default=None, max_length=2000)


class LeadOut(BaseModel):
    id: uuid.UUID
    pool_type: str
    customer_name: str
    customer_phone_masked: str | None = None
    city_id: uuid.UUID | None = None
    requirement: str | None = None
    assigned_dealer_id: uuid.UUID | None = None
    assigned_at: datetime | None = None
    status: str
    signed_amount: Decimal | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DealerCreate(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(min_length=1, max_length=50)
    contact_phone: str = Field(pattern=r"^\+?[0-9 -]{7,20}$")
    wecom_id: str | None = Field(default=None, max_length=100)
    city_id: uuid.UUID | None = None
    level: Literal["A", "B", "C"] = "C"
    annual_sales: Decimal | None = Field(default=None, ge=0, le=9_999_999_999_999)


class DealerUpdate(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_name: str | None = Field(default=None, min_length=1, max_length=50)
    contact_phone: str | None = Field(default=None, pattern=r"^\+?[0-9 -]{7,20}$")
    wecom_id: str | None = Field(default=None, max_length=100)
    city_id: uuid.UUID | None = None
    level: Literal["A", "B", "C"] | None = None
    annual_sales: Decimal | None = Field(default=None, ge=0, le=9_999_999_999_999)
    status: Literal["active", "paused", "disabled"] | None = None


class DealerLevelUpdate(BaseModel):
    level: Literal["A", "B", "C"]


class DealerOut(BaseModel):
    id: uuid.UUID
    company_name: str
    contact_name: str
    contact_phone: str
    wecom_id: str | None = None
    city_id: uuid.UUID | None = None
    level: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RiskCheckRequest(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)
    platform: str | None = Field(default=None, max_length=20)
    content_id: uuid.UUID | None = None


class RiskWordCreate(BaseModel):
    word: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=20)
    severity: Literal["low", "medium", "high"]
    platform: str | None = Field(default=None, max_length=20)
    suggestion: str | None = Field(default=None, max_length=2000)
    is_active: bool = True


class RiskWordUpdate(BaseModel):
    word: str | None = Field(default=None, min_length=1, max_length=100)
    category: str | None = Field(default=None, min_length=1, max_length=20)
    severity: Literal["low", "medium", "high"] | None = None
    platform: str | None = Field(default=None, max_length=20)
    suggestion: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class WeComCallbackRequest(BaseModel):
    # 开发测试模式字段（向后兼容；加密模式下可为空）
    sender_id: str = Field(default="", max_length=200)
    sender_name: str = Field(default="经销商", max_length=200)
    content: str = Field(default="", max_length=10000)
    # 企微真实回调加密模式字段
    msg_signature: str | None = Field(default=None, max_length=100)
    timestamp: str | None = Field(default=None, max_length=30)
    nonce: str | None = Field(default=None, max_length=200)
    encrypt: str | None = Field(default=None, max_length=2_000_000)


class WeComSendLeadRequest(BaseModel):
    lead_id: uuid.UUID


class WeComSendRemindRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=200)
    content_title: str = Field(min_length=1, max_length=200)
    scheduled_time: str = Field(min_length=1, max_length=100)


class WeComSendReportRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=200)
    report_data: dict | None = None
    report_type: str | None = Field(default=None, max_length=50)

    @field_validator("report_data")
    @classmethod
    def validate_report_data(cls, value: dict | None) -> dict | None:
        if (
            value is not None
            and len(json.dumps(value, ensure_ascii=False, default=str)) > 50_000
        ):
            raise ValueError("report_data 不能超过 50000 个字符")
        return value


class CalendarStatusUpdate(BaseModel):
    publish_status: Literal["pending", "published", "skipped", "failed"]


class CalendarRemindRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=200)
    content_title: str = Field(min_length=1, max_length=200)
    scheduled_time: str = Field(min_length=1, max_length=100)
    calendar_id: uuid.UUID | None = None


class RiskBatchItem(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)


class RiskBatchCheckRequest(BaseModel):
    contents: list[str | RiskBatchItem] = Field(min_length=1, max_length=100)

    @field_validator("contents")
    @classmethod
    def validate_string_items(
        cls, value: list[str | RiskBatchItem]
    ) -> list[str | RiskBatchItem]:
        if any(
            isinstance(item, str) and (not item.strip() or len(item) > 50_000)
            for item in value
        ):
            raise ValueError("批量检测内容不能为空且单条最多 50000 个字符")
        return value
