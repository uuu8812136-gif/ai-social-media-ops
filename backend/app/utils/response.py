from typing import Any

from pydantic import BaseModel


class PaginationMeta(BaseModel):
    page: int = 1
    page_size: int = 20
    total: int = 0


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: Any = None
    pagination: PaginationMeta | None = None


def success(
    data: Any = None, message: str = "success", pagination: PaginationMeta | None = None
) -> dict:
    return ApiResponse(
        code=0, message=message, data=data, pagination=pagination
    ).model_dump()


def error(code: int, message: str, data: Any = None) -> dict:
    return ApiResponse(code=code, message=message, data=data).model_dump()
