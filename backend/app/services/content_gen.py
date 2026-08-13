import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Content
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.social_account import SocialAccount
from app.services.llm_client import LLMClient
from app.services.risk_check import RiskCheckService
from app.utils.llm_json import clean_model_text, extract_json_object
from app.utils.social_text import sanitize_publish_text

logger = logging.getLogger(__name__)


@dataclass
class ScriptRequest:
    account_id: uuid.UUID
    topic: str
    strategy_type: str
    duration: str = "30s"
    style: str = ""
    local_cities: list[str] | None = None
    count: int = 1


@dataclass
class CopywritingRequest:
    account_id: uuid.UUID
    topic: str
    strategy_type: str
    platform: str = "douyin"
    count: int = 1


class ContentGenerationService:
    STRATEGIES = {
        "brand": {
            "tone": "专业、权威、品牌调性",
            "knowledge_base_id": "brand_kb",
            "forbidden": "个人化表达",
        },
        "ip": {
            "tone": "亲民、真实、个人口吻",
            "knowledge_base_id": "ip_kb",
            "forbidden": "品牌营销硬广",
        },
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = LLMClient(db)
        self.risk_service = RiskCheckService(db)

    def script_body_text(self, parsed: dict[str, Any]) -> str:
        # hook/body/cta 是模型内部结构，实际发布只保留文案内容。
        # 以结构化对象传给清洗器，避免正文内容刚好是“正文/钩子”等词时
        # 被误当成独立标题行删掉。
        return sanitize_publish_text(
            {
                field: self._as_text(parsed.get(field))
                for field in ("hook", "body", "cta")
            }
        )

    def copy_body_text(self, parsed: dict[str, Any], fallback: str) -> str:
        return sanitize_publish_text(
            self._as_text(parsed.get("body_text") or parsed.get("body") or fallback)
        )

    @staticmethod
    def _as_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value).strip()

    @staticmethod
    def _normalize_tags(value: Any) -> list[str]:
        if isinstance(value, str):
            values = re.split(r"[,，、\s]+", value)
        elif isinstance(value, list):
            values = value
        else:
            values = []
        result: list[str] = []
        for item in values:
            tag = str(item or "").strip().lstrip("#")
            if tag and tag not in result:
                result.append(tag)
        return result[:20]

    def parse_script_response(self, raw: Any, fallback_title: str) -> dict[str, Any]:
        parsed = extract_json_object(raw) or {}
        if not parsed:
            parsed = {
                "title": fallback_title,
                "hook": "",
                "body": clean_model_text(raw),
                "cta": "",
                "tags": [],
                "localizations": {},
            }
        return {
            "title": self._as_text(parsed.get("title"))[:200] or fallback_title,
            "hook": self._as_text(parsed.get("hook")),
            "body": self._as_text(parsed.get("body") or parsed.get("body_text")),
            "cta": self._as_text(parsed.get("cta")),
            "tags": self._normalize_tags(parsed.get("tags")),
            "localizations": parsed.get("localizations")
            if isinstance(parsed.get("localizations"), dict)
            else {},
        }

    def parse_copy_response(self, raw: Any, fallback_title: str) -> dict[str, Any]:
        parsed = extract_json_object(raw) or {}
        body = (
            self._as_text(parsed.get("body_text") or parsed.get("body"))
            if parsed
            else clean_model_text(raw)
        )
        return {
            "title": self._as_text(parsed.get("title"))[:200] or fallback_title,
            "body": body,
            "body_text": body,
            "tags": self._normalize_tags(parsed.get("tags")),
        }

    def normalize_stored_body(self, content_type: str, text: str) -> str:
        try:
            parsed = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return sanitize_publish_text(text)
        if not isinstance(parsed, dict):
            return text
        if content_type == "video_script":
            return self.script_body_text(parsed)
        return self.copy_body_text(parsed, text)

    def fallback_localizations(
        self, text: str, cities: list[str]
    ) -> list[dict[str, Any]]:
        first_line = text.strip().splitlines()[0] if text.strip() else "本地化内容"
        title = first_line.replace("#", "").strip()[:36] or "本地化内容"
        return [
            {
                "city": city,
                "title": f"{city}{title}",
                "body_text": text if city in text else f"{city}版本：{text}",
                "tags": [city, "本地化改写"],
            }
            for city in cities
        ]

    def load_strategy(self, strategy_type: str) -> dict:
        return self.STRATEGIES.get(strategy_type, self.STRATEGIES["ip"])

    async def get_account_info(self, account_id: uuid.UUID) -> SocialAccount | None:
        result = await self.db.execute(
            select(SocialAccount).where(
                SocialAccount.id == account_id,
                SocialAccount.status == "active",
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def account_display_name(account: SocialAccount | None) -> str:
        if not account:
            return "未关联账号"
        info = account.user_info or {}
        return str(
            account.nickname
            or info.get("name")
            or info.get("username")
            or account.platform_uid
            or account.platform
        )

    def _keyword_terms(self, values: list[str | None]) -> list[str]:
        terms: list[str] = []
        for value in values:
            if not value:
                continue
            text = str(value).strip()
            if text:
                terms.append(text)
            for part in re.split(r"[\s,，。；;:：、!！?？()\[\]（）/\\|]+", text):
                token = part.strip()
                if 2 <= len(token) <= 40:
                    terms.append(token)

        cleaned: list[str] = []
        seen: set[str] = set()
        for term in terms:
            if term not in seen:
                seen.add(term)
                cleaned.append(term)
        return cleaned[:12]

    def _score_knowledge(
        self,
        document: KnowledgeDocument,
        chunk: KnowledgeChunk,
        terms: list[str],
        strategy_type: str | None,
        cities: list[str] | None,
    ) -> int:
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
        score = 0
        for term in terms:
            token = term.lower()
            if token and token in haystack:
                score += 1
            if token and token in (document.title or "").lower():
                score += 2
        if strategy_type and document.strategy_type == strategy_type:
            score += 3
        if cities and document.city in cities:
            score += 2
        return score

    async def retrieve_knowledge(
        self,
        topic: str | None,
        strategy_type: str | None = None,
        cities: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        terms = self._keyword_terms([topic, strategy_type, *(cities or [])])
        conditions = [KnowledgeDocument.status == "active"]
        if strategy_type:
            conditions.append(
                or_(
                    KnowledgeDocument.strategy_type == strategy_type,
                    KnowledgeDocument.strategy_type.is_(None),
                    KnowledgeDocument.strategy_type == "",
                )
            )
        if cities:
            conditions.append(
                or_(
                    KnowledgeDocument.city.in_(cities),
                    KnowledgeDocument.city.is_(None),
                    KnowledgeDocument.city == "",
                )
            )
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

        try:
            result = await self.db.execute(
                select(KnowledgeChunk, KnowledgeDocument)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeChunk.document_id,
                )
                .where(*conditions)
                .order_by(
                    KnowledgeDocument.updated_at.desc(),
                    KnowledgeChunk.chunk_index.asc(),
                )
                .limit(max(limit * 8, 20))
            )
        except SQLAlchemyError as exc:
            await self.db.rollback()
            logger.warning("Knowledge retrieval skipped: %s", exc)
            return []

        scored: list[tuple[int, KnowledgeChunk, KnowledgeDocument]] = []
        for chunk, document in result.all():
            scored.append(
                (
                    self._score_knowledge(
                        document, chunk, terms, strategy_type, cities
                    ),
                    chunk,
                    document,
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)

        references: list[dict[str, Any]] = []
        for score, chunk, document in scored[:limit]:
            references.append(
                {
                    "document_id": str(document.id),
                    "chunk_id": str(chunk.id),
                    "title": document.title,
                    "source": document.source,
                    "city": document.city,
                    "category": document.category,
                    "tags": document.tags or chunk.tags or [],
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "score": score,
                }
            )
        return references

    def format_knowledge_prompt(self, references: list[dict[str, Any]]) -> str:
        if not references:
            return ""
        lines = ["可参考的知识库片段（用于事实、案例和本地化表达，避免编造来源）："]
        for index, item in enumerate(references, start=1):
            source = item.get("source") or item.get("title") or "知识库资料"
            city = f" / {item['city']}" if item.get("city") else ""
            content = str(item.get("content") or "").strip().replace("\n", " ")
            lines.append(
                f"[{index}] {item.get('title')}{city}｜来源：{source}｜{content[:500]}"
            )
        lines.append("生成结果如使用上述片段，请保留 knowledge_references 供系统展示。")
        return "\n".join(lines)

    def build_prompt(
        self,
        topic: str,
        strategy: dict,
        account_name: str,
        local_cities: list[str] | None,
        duration: str,
        style: str,
        knowledge_context: str = "",
    ) -> str:
        cities = "、".join(local_cities or [])
        knowledge_block = f"\n{knowledge_context}\n" if knowledge_context else "\n"
        return (
            f"你是社媒内容创作助手。\n"
            f"选题/topic: {topic}\n"
            f"账号: {account_name}\n"
            f"策略调性: {strategy['tone']}\n"
            f"禁忌: {strategy['forbidden']}\n"
            f"时长: {duration}\n"
            f"风格: {style}\n"
            f"本地化城市: {cities}\n"
            f"{knowledge_block}"
            f"只返回一个合法 JSON 对象，不要使用 Markdown 代码块或补充解释。"
            f"字段必须包含 title, hook, body, cta, tags, localizations。"
        )

    async def rag_enhance(
        self,
        result: dict,
        knowledge_base: str,
        references: list[dict[str, Any]] | None = None,
    ) -> dict:
        result["enhanced"] = True
        result["knowledge_base"] = knowledge_base
        result["knowledge_references"] = references or []
        return result

    async def generate_script(self, request: ScriptRequest) -> list[dict[str, Any]]:
        strategy = self.load_strategy(request.strategy_type)
        account_info = await self.get_account_info(request.account_id)
        account_name = self.account_display_name(account_info)
        knowledge_references = await self.retrieve_knowledge(
            topic=request.topic,
            strategy_type=request.strategy_type,
            cities=request.local_cities,
            limit=5,
        )
        knowledge_context = self.format_knowledge_prompt(knowledge_references)
        prompt = self.build_prompt(
            request.topic,
            strategy,
            account_name,
            request.local_cities,
            request.duration,
            request.style,
            knowledge_context,
        )

        model_name = await self.llm.get_model_name()
        raw_results = await self.llm.generate(
            model=model_name, prompt=prompt, n=request.count, temperature=0.7
        )

        scripts = []
        for raw in raw_results:
            parsed = self.parse_script_response(raw, request.topic)

            parsed = await self.rag_enhance(
                parsed, strategy["knowledge_base_id"], knowledge_references
            )
            body_text = self.script_body_text(parsed)
            risk = await self.risk_service.check(
                f"{parsed.get('title', request.topic)}\n{body_text}"
            )
            parsed["risk_check"] = risk.to_dict()

            content = Content(
                account_id=request.account_id,
                content_type="video_script",
                strategy_type=request.strategy_type,
                title=parsed.get("title", request.topic),
                body_text=body_text,
                tags=parsed.get("tags", []),
                ai_model=model_name,
                ai_prompt_snapshot=prompt,
                risk_check_result=risk.to_dict(),
                knowledge_references=knowledge_references,
                status="risk_checked" if risk.passed else "risk_failed",
            )
            self.db.add(content)
            await self.db.flush()
            parsed["content_id"] = str(content.id)
            parsed["body_text"] = body_text
            parsed["status"] = content.status
            scripts.append(parsed)

        await self.db.commit()
        return scripts

    async def generate_copywriting(
        self, request: CopywritingRequest
    ) -> list[dict[str, Any]]:
        strategy = self.load_strategy(request.strategy_type)
        account_info = await self.get_account_info(request.account_id)
        account_name = self.account_display_name(account_info)
        knowledge_references = await self.retrieve_knowledge(
            topic=request.topic,
            strategy_type=request.strategy_type,
            limit=5,
        )
        knowledge_context = self.format_knowledge_prompt(knowledge_references)
        prompt = (
            f"生成{request.platform}平台文案。\n"
            f"选题: {request.topic}\n"
            f"账号: {account_name}\n"
            f"调性: {strategy['tone']}\n"
            f"{knowledge_context}\n"
            f"只返回一个合法 JSON 对象，不要使用 Markdown 代码块或补充解释。"
            f"字段必须包含 title, body, tags。"
        )
        model_name = await self.llm.get_model_name()
        raw_results = await self.llm.generate(
            model=model_name, prompt=prompt, n=request.count, temperature=0.8
        )

        items = []
        for raw in raw_results:
            parsed = self.parse_copy_response(raw, request.topic)

            body_text = self.copy_body_text(parsed, raw)
            parsed["body_text"] = body_text
            parsed["knowledge_references"] = knowledge_references
            parsed["enhanced"] = bool(knowledge_references)
            parsed["knowledge_base"] = strategy["knowledge_base_id"]
            risk = await self.risk_service.check(
                f"{parsed.get('title', request.topic)}\n{body_text}"
            )
            parsed["risk_check"] = risk.to_dict()

            content = Content(
                account_id=request.account_id,
                content_type="image_text",
                strategy_type=request.strategy_type,
                title=parsed.get("title", request.topic),
                body_text=body_text,
                tags=parsed.get("tags", []),
                ai_model=model_name,
                ai_prompt_snapshot=prompt,
                risk_check_result=risk.to_dict(),
                knowledge_references=knowledge_references,
                status="risk_checked" if risk.passed else "risk_failed",
            )
            self.db.add(content)
            await self.db.flush()
            parsed["content_id"] = str(content.id)
            parsed["status"] = content.status
            items.append(parsed)

        await self.db.commit()
        return items

    async def rewrite_content_for_risk(
        self,
        content: Content,
        max_attempts: int = 3,
        platform: str | None = None,
        checked_by: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Rewrite a pre-publication item until deterministic risk checks pass."""
        current_title = content.title
        current_body = self.normalize_stored_body(
            content.content_type, content.body_text
        )
        current_tags = list(content.tags or [])
        model_name = await self.llm.get_model_name()
        attempts: list[dict[str, Any]] = []

        risk = await self.risk_service.check(
            f"{current_title}\n{current_body}", platform
        )
        if risk.passed:
            content.risk_check_result = risk.to_dict()
            content.status = "risk_checked"
            await self.risk_service.save_history(
                f"{current_title}\n{current_body}", risk, content.id, checked_by
            )
            await self.db.commit()
            return {
                "content": content,
                "attempts": attempts,
                "risk_result": risk.to_dict(),
            }

        for attempt in range(1, max(1, min(max_attempts, 3)) + 1):
            issue_payload = [issue.__dict__ for issue in risk.issues]
            fields = (
                "title, hook, body, cta, tags"
                if content.content_type == "video_script"
                else "title, body, tags"
            )
            prompt = (
                "你是社媒内容合规改写助手。请在不改变核心事实和营销目的的前提下改写内容，"
                "删除或替换所有风险表达，不得新增未经证实的数据、承诺或绝对化用语。\n"
                f"内容类型：{content.content_type}\n"
                f"当前标题：{current_title}\n"
                f"当前正文：{current_body}\n"
                f"当前标签：{current_tags}\n"
                f"必须解决的问题：{json.dumps(issue_payload, ensure_ascii=False)}\n"
                f"只返回一个合法 JSON 对象，不要使用 Markdown 代码块或解释，字段为：{fields}。"
            )
            raw = await self.llm.generate(
                model=model_name,
                prompt=prompt,
                n=1,
                temperature=0.25,
                max_tokens=1800,
            )
            if content.content_type == "video_script":
                parsed = self.parse_script_response(raw[0], current_title)
                rewritten_body = self.script_body_text(parsed)
            else:
                parsed = self.parse_copy_response(raw[0], current_title)
                rewritten_body = parsed["body_text"]

            rewritten_title = parsed["title"][:200] or current_title
            rewritten_tags = self._normalize_tags(parsed.get("tags")) or current_tags
            if rewritten_title == current_title and rewritten_body == current_body:
                attempts.append({"attempt": attempt, "changed": False, "passed": False})
                continue

            current_title = rewritten_title
            current_body = rewritten_body
            current_tags = rewritten_tags
            risk = await self.risk_service.check(
                f"{current_title}\n{current_body}", platform
            )
            await self.risk_service.save_history(
                f"{current_title}\n{current_body}", risk, content.id, checked_by
            )
            attempts.append(
                {
                    "attempt": attempt,
                    "changed": True,
                    "passed": risk.passed,
                    "issues": [issue.__dict__ for issue in risk.issues],
                }
            )
            if risk.passed:
                break

        content.title = current_title
        content.body_text = current_body
        content.tags = current_tags
        content.ai_model = model_name
        content.risk_check_result = risk.to_dict()
        content.status = "risk_checked" if risk.passed else "risk_failed"
        await self.db.commit()
        await self.db.refresh(content)
        return {"content": content, "attempts": attempts, "risk_result": risk.to_dict()}

    async def localize(
        self,
        cities: list[str],
        content_id: uuid.UUID | None = None,
        content_text: str | None = None,
        strategy_type: str | None = None,
        account_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        text = content_text
        if content_id and not text:
            result = await self.db.execute(
                select(Content).where(Content.id == content_id)
            )
            content = result.scalar_one_or_none()
            if not content:
                return []
            text = self.normalize_stored_body(content.content_type, content.body_text)

        if not text:
            return []

        topic = text.strip().splitlines()[0][:80] if text.strip() else ""
        knowledge_references = await self.retrieve_knowledge(
            topic=topic,
            strategy_type=strategy_type,
            cities=cities,
            limit=5,
        )
        knowledge_context = self.format_knowledge_prompt(knowledge_references)
        prompt = (
            f"将以下内容本地化为以下城市版本：{cities}\n原文：{text}\n{knowledge_context}\n"
            f"只返回一个合法 JSON 对象，不要使用 Markdown 代码块或补充解释。"
            f"key 为城市名，每个 value 包含 title、body_text、tags 字段。"
        )
        model_name = await self.llm.get_model_name()
        raw = await self.llm.generate(
            model=model_name, prompt=prompt, n=1, temperature=0.5
        )
        localizations = []
        try:
            parsed = extract_json_object(raw[0])
            if not isinstance(parsed, dict):
                raise ValueError("模型未返回城市本地化 JSON 对象")
            for city in cities:
                data = parsed.get(city) if isinstance(parsed, dict) else None
                if isinstance(data, dict):
                    localizations.append(
                        {
                            "city": city,
                            "title": self._as_text(data.get("title"))
                            or f"{city}本地化版本",
                            "body_text": self._as_text(
                                data.get("body_text") or data.get("body")
                            )
                            or text,
                            "tags": self._normalize_tags(data.get("tags")),
                            "knowledge_references": knowledge_references,
                        }
                    )
                else:
                    localizations.append(
                        {
                            "city": city,
                            "title": f"{city}本地化版本",
                            "body_text": text
                            if city in text
                            else f"{city}版本：{text}",
                            "tags": [city],
                            "knowledge_references": knowledge_references,
                        }
                    )
        except (TypeError, ValueError):
            localizations = self.fallback_localizations(text, cities)
            for item in localizations:
                item["knowledge_references"] = knowledge_references

        for item in localizations:
            risk = await self.risk_service.check(
                f"{item['title']}\n{item['body_text']}"
            )
            item["risk_check"] = risk.to_dict()
            item["status"] = "risk_checked" if risk.passed else "risk_failed"
            if account_id:
                content = Content(
                    account_id=account_id,
                    content_type="image_text",
                    strategy_type=strategy_type or "ip",
                    title=item["title"][:200],
                    body_text=item["body_text"],
                    tags=item.get("tags", []),
                    ai_model=model_name,
                    ai_prompt_snapshot=prompt,
                    risk_check_result=risk.to_dict(),
                    knowledge_references=knowledge_references,
                    status=item["status"],
                )
                self.db.add(content)
                await self.db.flush()
                item["content_id"] = str(content.id)

        if account_id:
            await self.db.commit()
        return localizations

    async def get_trending(self) -> list[dict[str, str]]:
        # No fake recommendations: stay empty until a real source is configured.
        return []
