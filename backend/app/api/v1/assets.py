import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import require_roles
from app.models.asset import AssetLibrary
from app.models.user import User
from app.schemas.common import AssetCreate, AssetOut, AssetUpdate
from app.services.storage import MinIOService
from app.utils.response import PaginationMeta, success

router = APIRouter(prefix="/assets", tags=["assets"])
logger = logging.getLogger(__name__)
settings = get_settings()


def _ensure_asset_access(asset: AssetLibrary, current_user: User) -> None:
    if current_user.role == "dealer" and not asset.is_public:
        raise HTTPException(status_code=404, detail="素材不存在")


def _asset_payload(asset: AssetLibrary, storage: MinIOService | None = None) -> dict:
    payload = AssetOut.model_validate(asset).model_dump()
    if storage is None:
        return payload
    try:
        source_url = asset.thumbnail_url or asset.file_url
        payload["preview_url"] = storage.get_browser_url(source_url)
    except Exception as exc:
        logger.warning("生成素材预览地址失败 asset_id=%s: %s", asset.id, exc)
    return payload


def _storage_or_none() -> MinIOService | None:
    try:
        return MinIOService()
    except Exception as exc:
        logger.warning("初始化素材存储客户端失败: %s", exc)
        return None


@router.get("/")
async def list_assets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    asset_type: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator", "dealer")),
):
    query = select(AssetLibrary)
    if current_user.role == "dealer":
        query = query.where(AssetLibrary.is_public.is_(True))
    if asset_type:
        query = query.where(AssetLibrary.asset_type == asset_type)
    if category:
        query = query.where(AssetLibrary.category == category)
    if keyword:
        query = query.where(AssetLibrary.title.ilike(f"%{keyword}%"))
    if tag:
        query = query.where(AssetLibrary.tags.contains([tag]))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(AssetLibrary.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    assets = result.scalars().all()
    storage = _storage_or_none()
    items = [_asset_payload(asset, storage) for asset in assets]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.post("/")
async def create_asset(
    body: AssetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    asset = AssetLibrary(**body.model_dump(), created_by=current_user.id)
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return success(_asset_payload(asset, _storage_or_none()))


@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),
    title: str = Query(..., min_length=1, max_length=200),
    asset_type: str = Query("image", pattern=r"^(image|video|document)$"),
    category: str | None = Query(default=None, max_length=100),
    description: str | None = Query(default=None, max_length=2000),
    is_public: bool = Query(False),
    tags: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    import json as _json

    content_type = (
        (file.content_type or "application/octet-stream")
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    allowed_types = set(settings.upload_allowed_mime_list)
    if allowed_types and content_type not in allowed_types:
        raise HTTPException(status_code=415, detail=f"不支持的文件类型: {content_type}")

    max_size = settings.UPLOAD_MAX_SIZE
    data = await file.read(max_size + 1)
    if len(data) > max_size:
        raise HTTPException(
            status_code=413, detail=f"文件超过上传限制（最大 {max_size} 字节）"
        )
    if not data:
        raise HTTPException(status_code=400, detail="上传文件不能为空")

    safe_filename = Path(file.filename or "file").name.strip() or "file"
    storage = MinIOService()
    try:
        file_url = storage.upload_file(data, safe_filename, content_type)
    except Exception as exc:
        logger.exception("MinIO 上传失败 filename=%s", safe_filename)
        raise HTTPException(status_code=502, detail="素材存储服务不可用") from exc
    tag_list: list[str] | None = None
    if tags:
        try:
            tag_list = _json.loads(tags)
            if not isinstance(tag_list, list):
                tag_list = None
        except Exception:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list is not None:
            tag_list = [str(tag).strip()[:100] for tag in tag_list if str(tag).strip()][
                :50
            ]
    asset = AssetLibrary(
        asset_type=asset_type,
        title=title,
        file_url=file_url,
        file_size=len(data),
        category=category,
        description=description,
        is_public=is_public,
        tags=tag_list,
        created_by=current_user.id,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return success(_asset_payload(asset, storage))


@router.get("/tags")
async def list_tags(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator", "dealer")),
):
    query = select(AssetLibrary.tags)
    if current_user.role == "dealer":
        query = query.where(AssetLibrary.is_public.is_(True))
    result = await db.execute(query)
    tags: set[str] = set()
    for row in result.scalars().all():
        if row:
            tags.update(row)
    return success({"tags": sorted(tags)})


@router.get("/{asset_id}")
async def get_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator", "dealer")),
):
    result = await db.execute(select(AssetLibrary).where(AssetLibrary.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    _ensure_asset_access(asset, current_user)
    return success(_asset_payload(asset, _storage_or_none()))


@router.put("/{asset_id}")
async def update_asset(
    asset_id: uuid.UUID,
    body: AssetUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(select(AssetLibrary).where(AssetLibrary.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(asset, field, value)
    await db.commit()
    await db.refresh(asset)
    return success(_asset_payload(asset, _storage_or_none()))


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(select(AssetLibrary).where(AssetLibrary.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    await db.delete(asset)
    await db.commit()
    return success(message="素材已删除")


@router.post("/{asset_id}/download")
async def download_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator", "dealer")),
):
    result = await db.execute(select(AssetLibrary).where(AssetLibrary.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    _ensure_asset_access(asset, current_user)
    asset.download_count += 1
    await db.commit()
    storage = MinIOService()
    try:
        temp_url = storage.get_browser_url(asset.file_url)
    except Exception as exc:
        logger.exception("生成素材下载地址失败 asset_id=%s", asset.id)
        raise HTTPException(status_code=502, detail="素材存储服务不可用") from exc
    return success({"download_url": temp_url, "expires_in": 3600})
