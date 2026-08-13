import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from minio import Minio
from redis.asyncio import Redis
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import engine
from app.core.exceptions import register_exception_handlers
from app.integrations.synapse_engine.utils.playwright_provider import (
    configure_windows_event_loop,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

# Windows 本地运行 uvicorn 时需 ProactorEventLoop 才能在 API 进程内启动 Playwright 子进程（扫码登录）。
# Linux/Docker 为 no-op，不影响生产部署。
configure_windows_event_loop()

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.seed import seed_data

    await seed_data()
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    debug=settings.APP_DEBUG,
    lifespan=lifespan,
    # 生产环境关闭 /docs /redoc /openapi.json 暴露
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)
register_exception_handlers(app)
app.include_router(api_router)


@app.get("/health")
@app.get("/health/live")
async def health_live():
    return {"status": "ok"}


async def _check_database() -> bool:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


async def _check_redis() -> bool:
    client = Redis.from_url(
        settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2
    )
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()


async def _check_minio() -> bool:
    client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )
    await asyncio.to_thread(client.list_buckets)
    return True


@app.get("/health/ready")
async def health_ready():
    async def run_check(name, check):
        try:
            return name, await asyncio.wait_for(check(), timeout=3)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Readiness check failed for %s: %s", name, exc
            )
            return name, False

    results = await asyncio.gather(
        *(
            run_check(name, check)
            for name, check in (
                ("database", _check_database),
                ("redis", _check_redis),
                ("storage", _check_minio),
            )
        )
    )
    checks = dict(results)

    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "unready", "checks": checks},
    )
