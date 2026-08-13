import uuid

import pytest
from fastapi import HTTPException

from app.api.v1.content import _apply_content_update
from app.models.content import Content
from app.schemas.content import ContentUpdate
from app.services.content_gen import ContentGenerationService
from app.services.risk_check import RiskCheckResult, RiskCheckService, RiskIssue
from app.utils.llm_json import extract_json_object, extract_json_value
from app.utils.social_text import sanitize_publish_text


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _content):
        return None


class FakeLLM:
    async def get_model_name(self):
        return "test-model"

    async def generate(self, **_kwargs):
        return [
            "```json\n"
            '{"title":"阳台封窗怎么选","hook":"先看需求",'
            '"body":"按环境和预算比较方案。","cta":"到店了解",'
            '"tags":["门窗","装修"]}'
            "\n```"
        ]


class FakeRiskService:
    def __init__(self):
        self.calls = 0

    async def check(self, _content, _platform=None):
        self.calls += 1
        if self.calls == 1:
            return RiskCheckResult(
                passed=False,
                issues=[
                    RiskIssue(
                        word="第一",
                        category="absolute_claim",
                        severity="high",
                        suggestion="改为客观描述",
                    )
                ],
                suggestion="改为客观描述",
            )
        return RiskCheckResult(passed=True, suggestion="内容合规，可以发布")

    async def save_history(self, *_args, **_kwargs):
        return None


def test_extracts_fenced_and_embedded_json():
    fenced = '```json\n{"title":"测试","body":"正文"}\n```'
    embedded = '以下是结果：\n{"title":"测试","body":"正文"}\n请查收'

    assert extract_json_object(fenced) == {"title": "测试", "body": "正文"}
    assert extract_json_value(embedded)["body"] == "正文"


def test_script_parser_never_exposes_markdown_json_wrapper():
    service = ContentGenerationService(FakeDB())
    raw = '```json\n{"title":"标题","hook":"开头","body":"正文","cta":"行动","tags":["#装修"]}\n```'

    parsed = service.parse_script_response(raw, "备用标题")
    body = service.script_body_text(parsed)

    assert parsed["title"] == "标题"
    assert parsed["tags"] == ["装修"]
    assert "```" not in body
    assert '"hook"' not in body
    assert body == "开头\n正文\n行动"
    assert "钩子：" not in body
    assert "正文：" not in body


def test_publish_text_removes_old_structure_labels_and_localization_metadata():
    old_body = (
        "**开场钩子：** 先看需求\n"
        "正文：按环境和预算比较方案。\n"
        "行动引导：到店了解\n"
        "本地化建议：广州：换成本地案例"
    )

    cleaned = sanitize_publish_text(old_body)

    assert cleaned == "先看需求\n按环境和预算比较方案。\n到店了解"
    assert "本地化建议" not in cleaned


def test_publish_text_flattens_legacy_json_without_field_names():
    cleaned = sanitize_publish_text(
        '{"hook":"先看需求","body":"比较方案","cta":"欢迎咨询",'
        '"localizations":{"广州":"本地版本"}}'
    )

    assert cleaned == "先看需求\n比较方案\n欢迎咨询"


def test_risk_issues_are_deduplicated():
    issues = [
        RiskIssue("第一", "absolute_claim", "high", "避免绝对化用语"),
        RiskIssue("第一", "absolute_claim", "high", "避免绝对化用语"),
    ]

    result = RiskCheckService.deduplicate_issues(issues)

    assert len(result) == 1


def test_manual_edit_clears_stale_risk_and_resets_status():
    content = Content(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        content_type="image_text",
        strategy_type="ip",
        title="原标题",
        body_text="原正文",
        tags=[],
        status="risk_checked",
        risk_check_result={"passed": True},
    )

    _apply_content_update(content, ContentUpdate(body_text="修改后的正文"))

    assert content.body_text == "修改后的正文"
    assert content.risk_check_result is None
    assert content.status == "ai_generated"


def test_content_cannot_be_approved_without_passed_risk_result():
    content = Content(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        content_type="image_text",
        strategy_type="ip",
        title="标题",
        body_text="正文",
        tags=[],
        status="risk_failed",
        risk_check_result={"passed": False},
    )

    with pytest.raises(HTTPException) as exc:
        _apply_content_update(content, ContentUpdate(status="approved"))

    assert exc.value.status_code == 400
    assert "风控未通过" in exc.value.detail


@pytest.mark.asyncio
async def test_ai_risk_rewrite_updates_content_and_recovers_status():
    service = ContentGenerationService(FakeDB())
    service.llm = FakeLLM()
    service.risk_service = FakeRiskService()
    content = Content(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        content_type="video_script",
        strategy_type="ip",
        title="行业第一选择",
        body_text="这是最好的方案",
        tags=["门窗"],
        status="risk_failed",
        risk_check_result={"passed": False},
    )

    result = await service.rewrite_content_for_risk(content, max_attempts=3)

    assert result["risk_result"]["passed"] is True
    assert result["attempts"][-1]["passed"] is True
    assert content.status == "risk_checked"
    assert content.title == "阳台封窗怎么选"
    assert "按环境和预算比较方案" in content.body_text
    assert "```" not in content.body_text
