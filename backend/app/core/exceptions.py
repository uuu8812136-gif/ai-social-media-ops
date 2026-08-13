import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.services.llm_client import LLMError
from app.utils.response import error

logger = logging.getLogger(__name__)


def public_validation_errors(exc: RequestValidationError) -> list[dict]:
    """Return useful validation details without echoing request data or internals."""
    public_keys = {"type", "loc", "msg"}
    return [
        {key: value for key, value in item.items() if key in public_keys}
        for item in exc.errors()
    ]


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(LLMError)
    async def llm_exception_handler(request: Request, exc: LLMError):
        logger.warning("LLM request failed: %s", exc)
        return JSONResponse(
            status_code=exc.status_code, content=error(exc.status_code, str(exc))
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code, content=error(exc.status_code, str(exc.detail))
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        return JSONResponse(
            status_code=422,
            content=error(422, "请求参数校验失败", public_validation_errors(exc)),
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error: %s", exc)
        return JSONResponse(status_code=500, content=error(500, "服务器内部错误"))
