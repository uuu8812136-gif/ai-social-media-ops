import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Tag = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class KnowledgeDocumentCreate(RequestModel):
    title: str = Field(..., min_length=1, max_length=200)
    kb_type: str = Field(default="content", min_length=1, max_length=50)
    strategy_type: Literal["ip", "brand"] | None = None
    city: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=80)
    tags: list[Tag] = Field(default_factory=list, max_length=50)
    source: str | None = Field(default=None, max_length=300)
    content: str = Field(..., min_length=1, max_length=1_000_000)
    status: Literal["active", "inactive"] = "active"


class KnowledgeDocumentUpdate(RequestModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    kb_type: str | None = Field(default=None, min_length=1, max_length=50)
    strategy_type: Literal["ip", "brand"] | None = None
    city: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=80)
    tags: list[Tag] | None = Field(default=None, max_length=50)
    source: str | None = Field(default=None, max_length=300)
    content: str | None = Field(default=None, min_length=1, max_length=1_000_000)
    status: Literal["active", "inactive"] | None = None


class KnowledgeChunkOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    content: str
    keywords: list | None = None
    tags: list | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeDocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    kb_type: str
    strategy_type: str | None = None
    city: str | None = None
    category: str | None = None
    tags: list | None = None
    source: str | None = None
    content: str
    status: str
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    chunk_count: int = 0

    model_config = {"from_attributes": True}


class KnowledgeDocumentDetailOut(KnowledgeDocumentOut):
    chunks: list[KnowledgeChunkOut] = Field(default_factory=list)


class KnowledgeSearchRequest(RequestModel):
    q: str | None = Field(default=None, max_length=500)
    topic: str | None = Field(default=None, max_length=500)
    strategy_type: Literal["ip", "brand"] | None = None
    cities: list[Tag] = Field(default_factory=list, max_length=20)
    kb_type: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=80)
    tags: list[Tag] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=5, ge=1, le=20)


class KnowledgeSearchResult(BaseModel):
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    title: str
    chunk_index: int
    content: str
    source: str | None = None
    city: str | None = None
    category: str | None = None
    tags: list | None = None
    score: int
