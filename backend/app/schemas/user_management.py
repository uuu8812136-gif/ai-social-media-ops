import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, field_validator


ROLE = Literal["admin", "operator", "dealer"]


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _validate_password(value: str) -> str:
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("密码必须同时包含字母和数字")
    return value


class SystemUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    full_name: str = Field(min_length=1, max_length=100)
    role: ROLE = "operator"
    password: str = Field(min_length=8, max_length=128)
    dealer_id: uuid.UUID | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]+", value):
            raise ValueError("用户名只能包含小写字母、数字、下划线、点和连字符")
        return value

    @field_validator("full_name")
    @classmethod
    def strip_full_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("姓名不能为空")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password(value)


class SystemUserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: ROLE | None = None
    dealer_id: uuid.UUID | None = None
    is_active: bool | None = None

    @field_validator("full_name")
    @classmethod
    def strip_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("姓名不能为空")
        return value


class SystemUserPasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password(value)


class SystemUserView(BaseModel):
    id: uuid.UUID
    username: str
    full_name: str
    role: ROLE
    dealer_id: uuid.UUID | None = None
    dealer_name: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
