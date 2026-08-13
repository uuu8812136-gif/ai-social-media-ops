"""Mock embedding provider for knowledge base vector operations."""

import hashlib
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class MockEmbeddingProvider:
    """Mock embedding provider that generates deterministic pseudo-vectors."""

    DIMENSION = 128

    def embed(self, text: str) -> list[float]:
        """Generate a deterministic pseudo-embedding vector."""
        if settings.MOCK_SCENARIO == "empty":
            return [0.0] * self.DIMENSION

        seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
        import random

        rng = random.Random(seed)
        vector = [rng.gauss(0, 1) for _ in range(self.DIMENSION)]
        norm = sum(x * x for x in vector) ** 0.5
        if norm > 0:
            vector = [x / norm for x in vector]
        return vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]

    def similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        if len(vec_a) != len(vec_b):
            return 0.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a * a for a in vec_a) ** 0.5
        norm_b = sum(b * b for b in vec_b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


class OpenAIEmbeddingProvider:
    """OpenAI text-embedding 真实 Provider。

    使用 httpx.Client 同步调用 OpenAI Embeddings API，
    维度 1536（text-embedding-3-small）。未配置 OPENAI_API_KEY 时
    返回全零向量并记录警告日志，与 Mock empty 场景行为一致。
    """

    DIMENSION = 1536

    def embed(self, text: str) -> list[float]:
        """调用 OpenAI Embeddings API 生成单条文本向量。"""
        if not settings.OPENAI_API_KEY:
            logger.warning("OpenAIEmbeddingProvider 未配置 OPENAI_API_KEY，返回零向量")
            return [0.0] * self.DIMENSION

        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{settings.OPENAI_BASE_URL}/embeddings",
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                    json={
                        "model": settings.OPENAI_EMBEDDING_MODEL,
                        "input": text,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            return data["data"][0]["embedding"]
        except Exception as exc:
            logger.error("OpenAIEmbeddingProvider.embed 失败: %s", exc)
            return [0.0] * self.DIMENSION

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量调用 OpenAI Embeddings API，input 为文本列表。"""
        if not settings.OPENAI_API_KEY:
            logger.warning("OpenAIEmbeddingProvider 未配置 OPENAI_API_KEY，返回零向量")
            return [[0.0] * self.DIMENSION for _ in texts]

        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{settings.OPENAI_BASE_URL}/embeddings",
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                    json={
                        "model": settings.OPENAI_EMBEDDING_MODEL,
                        "input": texts,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            # OpenAI 返回 data 各项含 index 字段，按 index 排序保证与输入顺序一致
            return [
                item["embedding"]
                for item in sorted(data["data"], key=lambda x: x.get("index", 0))
            ]
        except Exception as exc:
            logger.error("OpenAIEmbeddingProvider.embed_batch 失败: %s", exc)
            return [[0.0] * self.DIMENSION for _ in texts]

    def similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """余弦相似度，与 Mock 实现一致。"""
        if len(vec_a) != len(vec_b):
            return 0.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a * a for a in vec_a) ** 0.5
        norm_b = sum(b * b for b in vec_b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


def get_embedding_provider() -> MockEmbeddingProvider | OpenAIEmbeddingProvider:
    if settings.EMBEDDING_PROVIDER == "mock":
        return MockEmbeddingProvider()
    if settings.EMBEDDING_PROVIDER == "openai":
        return OpenAIEmbeddingProvider()
    raise NotImplementedError(
        f"Embedding provider '{settings.EMBEDDING_PROVIDER}' not implemented."
    )
