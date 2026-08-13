import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeChunkOut,
    KnowledgeDocumentCreate,
    KnowledgeDocumentDetailOut,
    KnowledgeDocumentOut,
    KnowledgeDocumentUpdate,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)
from app.utils.response import PaginationMeta, success

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _clean_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            seen.add(item)
            cleaned.append(item)
    return cleaned


def _extract_keywords(values: list[str | None], limit: int = 40) -> list[str]:
    words: list[str] = []
    for value in values:
        if not value:
            continue
        for part in re.split(r"[\s,;:!?()\[\]/\\|，。；：、！？（）]+", str(value)):
            token = part.strip()
            if 2 <= len(token) <= 40:
                words.append(token)
    return _clean_list(words)[:limit]


def _split_chunks(text: str, max_chars: int = 700) -> list[str]:
    source = (text or "").strip()
    if not source:
        return []

    parts = [
        part.strip()
        for part in re.split(r"\n\s*\n|(?<=[。！？!?])", source)
        if part.strip()
    ]
    chunks: list[str] = []
    current = ""
    for part in parts:
        if len(part) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(
                part[i : i + max_chars] for i in range(0, len(part), max_chars)
            )
            continue
        candidate = f"{current}\n{part}" if current else part
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks or [source[:max_chars]]


def _build_chunks(document: KnowledgeDocument) -> list[KnowledgeChunk]:
    tags = _clean_list(document.tags or [])
    metadata = [
        document.title,
        document.kb_type,
        document.strategy_type,
        document.city,
        document.category,
        document.source,
        *tags,
    ]
    return [
        KnowledgeChunk(
            document_id=document.id,
            chunk_index=index,
            content=content,
            keywords=_extract_keywords([*metadata, content]),
            tags=tags,
        )
        for index, content in enumerate(_split_chunks(document.content))
    ]


async def _rebuild_chunks(db: AsyncSession, document: KnowledgeDocument) -> int:
    await db.execute(
        delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
    )
    chunks = _build_chunks(document)
    db.add_all(chunks)
    await db.flush()
    return len(chunks)


def _serialize_document(document: KnowledgeDocument, chunk_count: int = 0) -> dict:
    data = KnowledgeDocumentOut.model_validate(document).model_dump()
    data["chunk_count"] = chunk_count
    return data


def _search_terms(body: KnowledgeSearchRequest) -> list[str]:
    values = [
        body.q,
        body.topic,
        body.strategy_type,
        body.category,
        *(body.cities or []),
        *(body.tags or []),
    ]
    direct = _clean_list([str(value) for value in values if value])
    return _clean_list([*direct, *_extract_keywords(values, limit=30)])[:12]


def _score_chunk(
    document: KnowledgeDocument,
    chunk: KnowledgeChunk,
    terms: list[str],
    body: KnowledgeSearchRequest,
) -> int:
    score = 0
    haystack = " ".join(
        [
            document.title or "",
            document.content or "",
            document.source or "",
            document.city or "",
            document.category or "",
            " ".join(document.tags or []),
            chunk.content or "",
            " ".join(chunk.keywords or []),
        ]
    ).lower()
    title = (document.title or "").lower()
    for term in terms:
        token = term.lower()
        if token and token in haystack:
            score += 1
        if token and token in title:
            score += 2
    if body.strategy_type and document.strategy_type == body.strategy_type:
        score += 3
    if body.cities and document.city in body.cities:
        score += 2
    return score


async def _search_knowledge(
    db: AsyncSession, body: KnowledgeSearchRequest
) -> list[dict]:
    terms = _search_terms(body)
    conditions = [KnowledgeDocument.status == "active"]
    if body.kb_type:
        conditions.append(KnowledgeDocument.kb_type == body.kb_type)
    if body.strategy_type:
        conditions.append(
            or_(
                KnowledgeDocument.strategy_type == body.strategy_type,
                KnowledgeDocument.strategy_type.is_(None),
                KnowledgeDocument.strategy_type == "",
            )
        )
    if body.category:
        conditions.append(KnowledgeDocument.category == body.category)
    if body.cities:
        conditions.append(
            or_(
                KnowledgeDocument.city.in_(body.cities),
                KnowledgeDocument.city.is_(None),
                KnowledgeDocument.city == "",
            )
        )
    if body.tags:
        for tag in body.tags[:5]:
            conditions.append(KnowledgeDocument.tags.cast(String).ilike(f"%{tag}%"))
    if terms:
        like_conditions = []
        for term in terms[:8]:
            pattern = f"%{term}%"
            like_conditions.extend(
                [
                    KnowledgeDocument.title.ilike(pattern),
                    KnowledgeDocument.content.ilike(pattern),
                    KnowledgeDocument.source.ilike(pattern),
                    KnowledgeDocument.city.ilike(pattern),
                    KnowledgeDocument.category.ilike(pattern),
                    KnowledgeDocument.tags.cast(String).ilike(pattern),
                    KnowledgeChunk.content.ilike(pattern),
                    KnowledgeChunk.keywords.cast(String).ilike(pattern),
                ]
            )
        conditions.append(or_(*like_conditions))

    result = await db.execute(
        select(KnowledgeChunk, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .where(*conditions)
        .order_by(KnowledgeDocument.updated_at.desc(), KnowledgeChunk.chunk_index.asc())
        .limit(max(body.limit * 10, 30))
    )
    scored: list[tuple[int, KnowledgeChunk, KnowledgeDocument]] = []
    for chunk, document in result.all():
        scored.append((_score_chunk(document, chunk, terms, body), chunk, document))
    scored.sort(key=lambda item: item[0], reverse=True)

    items: list[dict] = []
    for score, chunk, document in scored[: body.limit]:
        payload = KnowledgeSearchResult(
            document_id=document.id,
            chunk_id=chunk.id,
            title=document.title,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            source=document.source,
            city=document.city,
            category=document.category,
            tags=document.tags or chunk.tags,
            score=score,
        )
        items.append(payload.model_dump())
    return items


@router.get("/")
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    strategy_type: str | None = None,
    city: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    conditions = []
    if status:
        conditions.append(KnowledgeDocument.status == status)
    if strategy_type:
        conditions.append(KnowledgeDocument.strategy_type == strategy_type)
    if city:
        conditions.append(KnowledgeDocument.city == city)
    if q:
        pattern = f"%{q}%"
        conditions.append(
            or_(
                KnowledgeDocument.title.ilike(pattern),
                KnowledgeDocument.content.ilike(pattern),
                KnowledgeDocument.source.ilike(pattern),
                KnowledgeDocument.tags.cast(String).ilike(pattern),
            )
        )

    filtered = select(KnowledgeDocument.id).where(*conditions).subquery()
    total = await db.scalar(select(func.count()).select_from(filtered))
    chunk_counts = (
        select(
            KnowledgeChunk.document_id,
            func.count(KnowledgeChunk.id).label("chunk_count"),
        )
        .group_by(KnowledgeChunk.document_id)
        .subquery()
    )
    result = await db.execute(
        select(KnowledgeDocument, func.coalesce(chunk_counts.c.chunk_count, 0))
        .outerjoin(chunk_counts, chunk_counts.c.document_id == KnowledgeDocument.id)
        .where(KnowledgeDocument.id.in_(select(filtered.c.id)))
        .order_by(KnowledgeDocument.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [
        _serialize_document(document, int(chunk_count or 0))
        for document, chunk_count in result.all()
    ]
    return success(
        items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total or 0),
    )


@router.post("/")
async def create_document(
    body: KnowledgeDocumentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "operator")),
):
    payload = body.model_dump()
    payload["tags"] = _clean_list(body.tags)
    document = KnowledgeDocument(**payload, created_by=current_user.id)
    db.add(document)
    await db.flush()
    chunk_count = await _rebuild_chunks(db, document)
    await db.commit()
    await db.refresh(document)
    return success(_serialize_document(document, chunk_count))


@router.post("/search")
async def search_documents(
    body: KnowledgeSearchRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    items = await _search_knowledge(db, body)
    return success({"items": items, "total": len(items), "empty": len(items) == 0})


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    chunk_result = await db.execute(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.document_id == document.id)
        .order_by(KnowledgeChunk.chunk_index.asc())
    )
    chunks = chunk_result.scalars().all()
    data = _serialize_document(document, len(chunks))
    data["chunks"] = [
        KnowledgeChunkOut.model_validate(chunk).model_dump() for chunk in chunks
    ]
    return success(KnowledgeDocumentDetailOut(**data).model_dump())


@router.put("/{document_id}")
async def update_document(
    document_id: uuid.UUID,
    body: KnowledgeDocumentUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Knowledge document not found")

    rebuild_fields = {
        "title",
        "kb_type",
        "strategy_type",
        "city",
        "category",
        "tags",
        "source",
        "content",
    }
    payload = body.model_dump(exclude_unset=True)
    should_rebuild = bool(rebuild_fields.intersection(payload.keys()))
    if "tags" in payload:
        payload["tags"] = _clean_list(payload["tags"])
    for field, value in payload.items():
        setattr(document, field, value)
    if should_rebuild:
        chunk_count = await _rebuild_chunks(db, document)
    else:
        chunk_count = (
            await db.scalar(
                select(func.count()).where(KnowledgeChunk.document_id == document.id)
            )
            or 0
        )
    await db.commit()
    await db.refresh(document)
    return success(_serialize_document(document, int(chunk_count)))


@router.delete("/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    await db.execute(
        delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
    )
    await db.delete(document)
    await db.commit()
    return success(message="Knowledge document deleted")


@router.post("/{document_id}/rebuild")
async def rebuild_document_chunks(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    chunk_count = await _rebuild_chunks(db, document)
    await db.commit()
    await db.refresh(document)
    return success({"document_id": str(document.id), "chunk_count": chunk_count})
