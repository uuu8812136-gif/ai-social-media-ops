import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import RiskCheckHistory, RiskWord
from app.services.llm_client import LLMClient, LLMConfigurationError


@dataclass
class RiskIssue:
    word: str
    category: str
    severity: str
    suggestion: str = ""


@dataclass
class RiskCheckResult:
    passed: bool
    issues: list[RiskIssue] = field(default_factory=list)
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": [issue.__dict__ for issue in self.issues],
            "suggestion": self.suggestion,
        }


class RiskCheckService:
    AD_LAW_PATTERNS = [
        (r"最好|第一|唯一|顶级|极致", "absolute_claim", "high", "避免绝对化用语"),
        (r"100%|百分百|零风险", "absolute_claim", "high", "避免绝对化承诺"),
    ]
    INDUSTRY_PATTERNS = [
        (
            r"隔音\d+分贝",
            "industry_specific",
            "high",
            "门窗隔音效果需有实测依据，避免虚假数据",
        ),
        (r"永久|终身质保", "industry_specific", "medium", "质保表述需符合实际政策"),
    ]

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = LLMClient(db)

    async def check(self, content: str, platform: str | None = None) -> RiskCheckResult:
        from app.core.config import get_settings

        settings = get_settings()
        scenario = settings.MOCK_SCENARIO

        # Scenario: content_violation — 模拟内容违规
        if settings.AI_MOCK_MODE and scenario == "content_violation":
            return RiskCheckResult(
                passed=False,
                issues=[
                    RiskIssue(
                        word="模拟敏感词",
                        category="mock_violation",
                        severity="high",
                        suggestion="模拟内容违规：包含敏感信息",
                    )
                ],
                suggestion="模拟内容违规：包含敏感信息，已被拦截",
            )

        issues: list[RiskIssue] = []
        issues.extend(await self.match_sensitive_words(content, platform))
        issues.extend(self.check_ad_law(content))
        issues.extend(self.check_industry_rules(content))
        issues = self.deduplicate_issues(issues)

        if any(i.severity == "high" for i in issues):
            ai_issues = await self.llm_judge(content, [i.__dict__ for i in issues])
            for item in ai_issues:
                if isinstance(item, dict):
                    issues.append(
                        RiskIssue(
                            word=item.get("word", "AI检测"),
                            category=item.get("category", "ai_judge"),
                            severity=item.get("severity", "medium"),
                            suggestion=item.get("suggestion", ""),
                        )
                    )
        issues = self.deduplicate_issues(issues)

        high_count = len([i for i in issues if i.severity == "high"])
        return RiskCheckResult(
            passed=high_count == 0,
            issues=issues,
            suggestion=self.generate_suggestion(issues),
        )

    async def match_sensitive_words(
        self, content: str, platform: str | None = None
    ) -> list[RiskIssue]:
        query = select(RiskWord).where(RiskWord.is_active.is_(True))
        result = await self.db.execute(query)
        words = result.scalars().all()
        issues = []
        for w in words:
            if w.platform and platform and w.platform != platform:
                continue
            if w.word in content:
                issues.append(
                    RiskIssue(
                        word=w.word,
                        category=w.category,
                        severity=w.severity,
                        suggestion=w.suggestion or "",
                    )
                )
        return issues

    def check_ad_law(self, content: str) -> list[RiskIssue]:
        issues = []
        for pattern, category, severity, suggestion in self.AD_LAW_PATTERNS:
            for match in re.finditer(pattern, content):
                issues.append(
                    RiskIssue(
                        word=match.group(),
                        category=category,
                        severity=severity,
                        suggestion=suggestion,
                    )
                )
        return issues

    def check_industry_rules(self, content: str) -> list[RiskIssue]:
        issues = []
        for pattern, category, severity, suggestion in self.INDUSTRY_PATTERNS:
            for match in re.finditer(pattern, content):
                issues.append(
                    RiskIssue(
                        word=match.group(),
                        category=category,
                        severity=severity,
                        suggestion=suggestion,
                    )
                )
        return issues

    async def llm_judge(self, content: str, issues: list[dict]) -> list[dict]:
        try:
            return await self.llm.judge(content, issues)
        except LLMConfigurationError:
            # Deterministic rule checks remain functional before an administrator configures an LLM.
            return []

    def generate_suggestion(self, issues: list[RiskIssue]) -> str:
        if not issues:
            return "内容合规，可以发布"
        suggestions = [i.suggestion for i in issues if i.suggestion]
        unique_suggestions = list(dict.fromkeys(suggestions))
        return (
            "；".join(unique_suggestions)
            if unique_suggestions
            else "请修改高风险表述后重新检测"
        )

    @staticmethod
    def deduplicate_issues(issues: list[RiskIssue]) -> list[RiskIssue]:
        result: list[RiskIssue] = []
        seen: set[tuple[str, str, str]] = set()
        for issue in issues:
            key = (issue.word, issue.category, issue.severity)
            if key in seen:
                continue
            seen.add(key)
            result.append(issue)
        return result

    async def save_history(
        self,
        content: str,
        result: RiskCheckResult,
        content_id: uuid.UUID | None = None,
        checked_by: uuid.UUID | None = None,
    ) -> RiskCheckHistory:
        record = RiskCheckHistory(
            content_id=content_id,
            content_text=content,
            result=result.to_dict(),
            checked_by=checked_by,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record
