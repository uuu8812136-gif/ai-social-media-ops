"""数据采集 API。

路由前缀：/crawler
- GET  /platforms           支持的平台
- POST /jobs                创建采集任务
- GET  /jobs                任务列表
- GET  /jobs/{id}           任务详情
- POST /jobs/{id}/stop      停止任务
- POST /jobs/{id}/result    Worker 回写结果
- GET  /data/files          数据文件列表
- GET  /data/files/{path}    解析数据文件
- POST /data/import          导入采集数据到 contents/assets
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import require_roles
from app.models.crawler import CrawlerImportLog, CrawlerItem, CrawlerJob
from app.models.user import User
from app.utils.response import PaginationMeta, success

router = APIRouter(prefix="/crawler", tags=["crawler"])

settings = get_settings()
logger = logging.getLogger(__name__)


def _resolve_crawler_data_file(file_path: str) -> Path:
    from app.integrations.mediacrawler_engine.stores import resolve_data_file

    try:
        return resolve_data_file(file_path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        status_code = 413 if "大小" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


# ===== Schemas =====


class CrawlerSearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(min_length=1, max_length=20)

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        if not cleaned:
            raise ValueError("至少提供一个采集关键词")
        if any(len(value) > 100 for value in cleaned):
            raise ValueError("单个采集关键词不能超过 100 个字符")
        return list(dict.fromkeys(cleaned))


class CrawlerJobConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_notes: int = Field(default=20, ge=1, le=100)
    max_comments: int | None = Field(default=None, ge=0, le=100)


class CreateCrawlerJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    platform: Literal["xhs", "dy", "bili"]
    crawler_type: Literal["search"] = "search"
    params: CrawlerSearchParams
    config: CrawlerJobConfig = Field(default_factory=CrawlerJobConfig)


class ImportCrawlerDataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: uuid.UUID
    item_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    target: Literal["content"] = "content"
    account_id: uuid.UUID


class CrawlerResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    items_count: int = Field(default=0, ge=0, le=1_000_000)
    output_files: list[dict[str, Any] | str] = Field(
        default_factory=list, max_length=100
    )
    error: str | None = Field(default=None, max_length=5000)


# 各平台支持的采集类型（仅 search 已实现，creator/detail/comment 未实现）
_PLATFORM_SUPPORTED_MODES: dict[str, set[str]] = {
    "xhs": {"search"},
    "dy": {"search"},
    "bili": {"search"},
}


class CrawlerJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None = None
    platform: str
    crawler_type: str
    params: dict | None = None
    config: dict | None = None
    status: str
    items_count: int
    output_files: list | None = None
    error_message: str | None = None
    celery_task_id: str | None = None
    creator_id: uuid.UUID | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ===== 路由 =====


@router.get("/platforms")
async def list_platforms(
    _: User = Depends(require_roles("admin", "operator")),
):
    """列出采集平台及其真实能力状态（beta 可采 / planned 待接入）。"""
    from app.integrations.mediacrawler_engine.service import EmbeddedMediaCrawlerService
    from app.integrations.platform_capabilities import crawl_platforms

    service = EmbeddedMediaCrawlerService()
    return success(
        {
            "platforms": crawl_platforms(),
            "available": service.is_available(),
        }
    )


@router.post("/jobs")
async def create_crawler_job(
    body: CreateCrawlerJobRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    """创建采集任务并派发到 Celery worker。"""
    # 校验平台与采集类型：未实现的组合直接 400，不要让任务进 worker 后才失败
    supported_modes = _PLATFORM_SUPPORTED_MODES.get(body.platform)
    if supported_modes is None:
        raise HTTPException(
            status_code=400,
            detail=f"平台 {body.platform} 的采集器未接入，当前仅支持 xhs（小红书）、dy（抖音）、bili（B站）",
        )
    if body.crawler_type not in supported_modes:
        raise HTTPException(
            status_code=400,
            detail=(
                f"平台 {body.platform} 不支持采集类型 {body.crawler_type}，"
                f"当前仅支持：{', '.join(sorted(supported_modes))}（关键词搜索）"
            ),
        )

    params = body.params.model_dump()
    config = body.config.model_dump(exclude_none=True)
    job = CrawlerJob(
        name=body.name,
        platform=body.platform,
        crawler_type=body.crawler_type,
        params=params,
        config=config,
        status="queued",
        creator_id=current_user.id,
    )
    db.add(job)
    await db.flush()

    # 先提交任务记录，避免 worker 抢先执行时查不到 job。
    await db.commit()

    # 派发到 worker
    from app.integrations.mediacrawler_engine.workers.tasks import run_crawl_task

    task_spec = {
        "job_id": str(job.id),
        "platform": body.platform,
        "crawler_type": body.crawler_type,
        "params": params,
        "config_overrides": config,
        "save_dir": str(Path(settings.MEDIACRAWLER_DATA_DIR) / body.platform),
    }
    try:
        async_result = run_crawl_task.delay(task_spec)
        job.celery_task_id = getattr(async_result, "id", "")
    except Exception as exc:
        job.status = "dispatch_failed"
        job.error_message = "任务队列暂不可用，请稍后重新创建采集任务"
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        raise HTTPException(
            status_code=503, detail="任务队列暂不可用，采集任务已记录"
        ) from exc
    await db.commit()
    await db.refresh(job)

    return success(CrawlerJobOut.model_validate(job).model_dump())


@router.get("/jobs")
async def list_crawler_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    platform: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """采集任务列表。"""
    query = select(CrawlerJob)
    if platform:
        query = query.where(CrawlerJob.platform == platform)
    if status:
        query = query.where(CrawlerJob.status == status)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(CrawlerJob.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [
        CrawlerJobOut.model_validate(j).model_dump() for j in result.scalars().all()
    ]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.get("/jobs/{job_id}")
async def get_crawler_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """采集任务详情（含采集到的条目）。"""
    result = await db.execute(select(CrawlerJob).where(CrawlerJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="采集任务不存在")

    items_result = await db.execute(
        select(CrawlerItem)
        .where(CrawlerItem.job_id == job_id)
        .order_by(CrawlerItem.crawled_at.desc())
        .limit(100)
    )
    items = [
        {
            "id": str(i.id),
            "platform": i.platform,
            "platform_item_id": i.platform_item_id,
            "item_type": i.item_type,
            "title": i.title,
            "desc": i.desc,
            "author_name": i.author_name,
            "liked_count": i.liked_count,
            "collected_count": i.collected_count,
            "comment_count": i.comment_count,
            "share_count": i.share_count,
            "media_urls": i.media_urls,
            "crawled_at": i.crawled_at.isoformat() if i.crawled_at else None,
        }
        for i in items_result.scalars().all()
    ]
    return success({**CrawlerJobOut.model_validate(job).model_dump(), "items": items})


@router.post("/jobs/{job_id}/stop")
async def stop_crawler_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    """停止采集任务（标记为 cancelled，Celery 任务无法强制终止）。"""
    result = await db.execute(select(CrawlerJob).where(CrawlerJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="采集任务不存在")
    if job.status not in ("queued", "running", "pending"):
        raise HTTPException(status_code=400, detail=f"任务状态 {job.status} 无法停止")

    previous_status = job.status
    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc)
    await db.commit()

    if job.celery_task_id:
        try:
            from app.tasks.celery_app import celery_app

            celery_app.control.revoke(
                job.celery_task_id,
                terminate=previous_status == "running",
                signal="SIGTERM",
            )
        except Exception as exc:
            logger.warning("撤销采集任务失败 job_id=%s: %s", job.id, exc)
    return success({"job_id": str(job.id), "status": job.status})


@router.post("/jobs/{job_id}/result")
async def writeback_crawler_result(
    job_id: uuid.UUID,
    body: CrawlerResultRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    """Worker 回写采集结果。"""
    result = await db.execute(select(CrawlerJob).where(CrawlerJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="采集任务不存在")

    success_flag = body.success
    job.status = "succeeded" if success_flag else "failed"
    job.items_count = body.items_count
    job.output_files = body.output_files
    job.error_message = body.error
    job.finished_at = datetime.now(timezone.utc)

    # 解析采集到的条目并写入 crawler_items 表
    if success_flag and job.output_files:
        from app.integrations.mediacrawler_engine.stores import parse_data_file
        from app.integrations.mediacrawler_engine.workers.writeback import (
            _build_crawler_item,
        )

        await db.execute(delete(CrawlerItem).where(CrawlerItem.job_id == job.id))
        for f in job.output_files:
            file_path = f.get("path") if isinstance(f, dict) else f
            if not file_path:
                continue
            target = _resolve_crawler_data_file(str(file_path))
            items = parse_data_file(target)
            for item in items:
                ci = _build_crawler_item(job, item)
                if ci is not None:
                    db.add(ci)

    await db.commit()
    return success(
        {
            "job_id": str(job.id),
            "status": job.status,
            "items_count": job.items_count,
        }
    )


@router.get("/data/files")
async def list_data_files(
    platform: Literal["xhs", "dy", "bili"] | None = None,
    _: User = Depends(require_roles("admin", "operator")),
):
    """列出采集目录下的数据文件。"""
    from app.integrations.mediacrawler_engine.service import EmbeddedMediaCrawlerService

    service = EmbeddedMediaCrawlerService()
    files = service.list_data_files(platform)
    return success(files)


@router.get("/data/files/parse")
async def parse_data_file_api(
    file_path: str = Query(
        ..., max_length=4096, description="采集数据目录内的文件路径"
    ),
    _: User = Depends(require_roles("admin", "operator")),
):
    """解析数据文件为标准 dict 列表。"""
    from app.integrations.mediacrawler_engine.service import EmbeddedMediaCrawlerService

    service = EmbeddedMediaCrawlerService()
    target = _resolve_crawler_data_file(file_path)
    items = service.parse_file(str(target))
    return success(
        {
            "file_path": str(target),
            "items_count": len(items),
            "items": items[:50],  # 限制返回数量
        }
    )


@router.get("/data/files/download")
async def download_data_file(
    file_path: str = Query(
        ..., max_length=4096, description="采集数据目录内的文件路径"
    ),
    _: User = Depends(require_roles("admin", "operator")),
):
    """下载采集原始数据文件（限定在采集数据目录内，防止路径穿越）。"""
    from fastapi.responses import FileResponse

    target = _resolve_crawler_data_file(file_path)
    return FileResponse(
        str(target), filename=target.name, media_type="application/octet-stream"
    )


@router.post("/data/import")
async def import_crawler_data(
    body: ImportCrawlerDataRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    """把采集到的数据导入到 contents/assets。

    body:
    {
        "job_id": "uuid",
        "item_ids": ["uuid", ...],  # 可选，不传则导入整个 job 的所有条目
        "target": "content|asset",  # 默认 content
        "account_id": "uuid"        # 关联社媒账号 ID
    }
    """
    from app.models.social_account import SocialAccount

    job_id = body.job_id
    target = body.target
    item_ids = body.item_ids
    account_id = body.account_id

    job = await db.scalar(select(CrawlerJob).where(CrawlerJob.id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="采集任务不存在")
    account_exists = await db.scalar(
        select(SocialAccount.id).where(
            SocialAccount.id == account_id,
            SocialAccount.status == "active",
        )
    )
    if account_exists is None:
        raise HTTPException(status_code=422, detail="社媒账号不存在或已停用")

    # 加载采集条目
    query = select(CrawlerItem).where(CrawlerItem.job_id == job_id)
    if item_ids:
        query = query.where(CrawlerItem.id.in_(item_ids))
    items_result = await db.execute(query)
    items = items_result.scalars().all()

    if not items:
        return success({"imported": 0, "message": "没有可导入的条目"})

    existing_result = await db.execute(
        select(CrawlerImportLog.item_id).where(
            CrawlerImportLog.job_id == job_id,
            CrawlerImportLog.target == target,
            CrawlerImportLog.status == "success",
        )
    )
    already_imported = set(existing_result.scalars().all())

    imported = 0
    logs: list[CrawlerImportLog] = []
    for item in items:
        if item.id in already_imported:
            logs.append(
                CrawlerImportLog(
                    job_id=job_id,
                    item_id=item.id,
                    target=target,
                    status="skipped",
                    message="该采集条目已导入",
                )
            )
            continue

        from app.models.content import Content

        content = Content(
            account_id=account_id,
            content_type="crawled",
            strategy_type="imported",
            title=str(item.title or "采集导入")[:200],
            body_text=str(item.desc or ""),
            tags=[],
            media_urls=item.media_urls or [],
            status="draft",
        )
        db.add(content)
        await db.flush()
        logs.append(
            CrawlerImportLog(
                job_id=job_id,
                item_id=item.id,
                target="content",
                target_id=content.id,
                status="success",
            )
        )
        imported += 1

    for log in logs:
        db.add(log)
    await db.commit()

    return success(
        {
            "imported": imported,
            "total": len(items),
            "logs": [
                {
                    "item_id": str(log.item_id) if log.item_id else None,
                    "status": log.status,
                    "message": log.message,
                }
                for log in logs
            ],
        }
    )
