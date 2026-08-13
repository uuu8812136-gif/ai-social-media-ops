"""Notification provider.

Mock / WeCom / Email 通知实现：
- MockNotifyProvider: 模拟通知（开发场景）
- WeComNotifyProvider: 站内信走 logger，企微走 WeComNotifyService.send()
- EmailNotifyProvider: 通过 smtplib 发送邮件
"""

import logging
import os
import smtplib
import ssl
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class NotifyResult:
    def __init__(
        self,
        success: bool,
        channel: str,
        message_id: str,
        sent_at: str,
        error_message: str | None = None,
    ):
        self.success = success
        self.channel = channel
        self.message_id = message_id
        self.sent_at = sent_at
        self.error_message = error_message

    def to_dict(self) -> dict[str, Any]:
        result = {
            "success": self.success,
            "channel": self.channel,
            "message_id": self.message_id,
            "sent_at": self.sent_at,
        }
        if self.error_message:
            result["error_message"] = self.error_message
        return result


class DisabledNotifyProvider:
    """Explicit no-op provider used when notifications are intentionally disabled."""

    async def send(
        self,
        user_id: str,
        message_type: str,
        title: str,
        content: str,
        channel: str = "disabled",
    ) -> NotifyResult:
        logger.info("Notification disabled type=%s user_id=%s", message_type, user_id)
        return NotifyResult(
            success=True,
            channel="disabled",
            message_id="",
            sent_at=datetime.now(timezone.utc).isoformat(),
        )

    async def send_pending_review(
        self, content_title: str, reviewer_id: str
    ) -> NotifyResult:
        return await self.send(
            reviewer_id, "pending_review", "内容待审核", content_title
        )

    async def send_publish_success(
        self, content_title: str, platform: str, publisher_id: str
    ) -> NotifyResult:
        return await self.send(
            publisher_id, "publish_success", "发布成功", f"{content_title} / {platform}"
        )

    async def send_lead_alert(self, customer_name: str, dealer_id: str) -> NotifyResult:
        return await self.send(dealer_id, "lead_alert", "新线索提醒", customer_name)

    async def send_risk_alert(
        self, content_title: str, risk_words: list[str], operator_id: str
    ) -> NotifyResult:
        return await self.send(operator_id, "risk_alert", "风险词提醒", content_title)


class MockNotifyProvider:
    """Mock notification provider."""

    async def send(
        self,
        user_id: str,
        message_type: str,
        title: str,
        content: str,
        channel: str = "in_app",
    ) -> NotifyResult:
        scenario = settings.MOCK_SCENARIO
        message_id = f"notify_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        logger.info(
            "NotifyProvider.send user_id=%s type=%s channel=%s scenario=%s",
            user_id,
            message_type,
            channel,
            scenario,
        )

        if scenario == "notify_fail":
            return NotifyResult(
                success=False,
                channel=channel,
                message_id=message_id,
                sent_at=now,
                error_message="模拟通知发送失败：服务不可用",
            )

        if scenario == "timeout":
            import asyncio

            await asyncio.sleep(0.1)
            return NotifyResult(
                success=False,
                channel=channel,
                message_id=message_id,
                sent_at=now,
                error_message="模拟通知超时",
            )

        # Normal success
        logger.info("NotifyProvider.send success message_id=%s", message_id)
        return NotifyResult(
            success=True,
            channel=channel,
            message_id=message_id,
            sent_at=now,
        )

    async def send_pending_review(
        self, content_title: str, reviewer_id: str
    ) -> NotifyResult:
        return await self.send(
            user_id=reviewer_id,
            message_type="pending_review",
            title="内容待审核",
            content=f"新内容「{content_title}」已生成，请审核。",
            channel="in_app",
        )

    async def send_publish_success(
        self, content_title: str, platform: str, publisher_id: str
    ) -> NotifyResult:
        return await self.send(
            user_id=publisher_id,
            message_type="publish_success",
            title="发布成功",
            content=f"内容「{content_title}」已成功发布到{platform}。",
            channel="in_app",
        )

    async def send_lead_alert(self, customer_name: str, dealer_id: str) -> NotifyResult:
        return await self.send(
            user_id=dealer_id,
            message_type="lead_alert",
            title="新线索提醒",
            content=f"收到新客户「{customer_name}」的咨询，请1小时内联系。",
            channel="wecom",
        )

    async def send_risk_alert(
        self, content_title: str, risk_words: list[str], operator_id: str
    ) -> NotifyResult:
        return await self.send(
            user_id=operator_id,
            message_type="risk_alert",
            title="风险词提醒",
            content=f"内容「{content_title}」包含风险词：{', '.join(risk_words)}，请检查。",
            channel="in_app",
        )


class WeComNotifyProvider:
    """企微应用消息通知 Provider。

    channel="wecom" 时实际调用企微应用消息接口（委托 WeComNotifyService.send）；
    channel="in_app" 时仅 logger 记录，站内信由前端轮询拉取。
    """

    def __init__(self):
        from app.services.wecom_notify import WeComNotifyService

        self._wecom_cls = WeComNotifyService

    async def send(
        self,
        user_id: str,
        message_type: str,
        title: str,
        content: str,
        channel: str = "in_app",
    ) -> NotifyResult:
        message_id = f"notify_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        logger.info(
            "WeComNotifyProvider.send user_id=%s type=%s channel=%s",
            user_id,
            message_type,
            channel,
        )

        if channel == "wecom":
            # 委托企微应用消息发送（WeComNotifyService.send 不依赖 db）
            service = self._wecom_cls(db=None)
            text = f"【{title}】\n{content}"
            try:
                resp = await service.send(user_id, text)
                errcode = resp.get("errcode", -1)
                ok = errcode == 0
                return NotifyResult(
                    success=ok,
                    channel=channel,
                    message_id=message_id,
                    sent_at=now,
                    error_message=None if ok else resp.get("errmsg", "企微发送失败"),
                )
            except Exception as e:
                logger.exception("WeComNotifyProvider 企微发送异常: %s", e)
                return NotifyResult(
                    success=False,
                    channel=channel,
                    message_id=message_id,
                    sent_at=now,
                    error_message=str(e),
                )

        # channel == "in_app" 或其它：站内信仅记录，由前端轮询
        logger.info(
            "WeComNotifyProvider in_app notify user_id=%s type=%s title=%s",
            user_id,
            message_type,
            title,
        )
        return NotifyResult(
            success=True,
            channel=channel,
            message_id=message_id,
            sent_at=now,
        )

    async def send_pending_review(
        self, content_title: str, reviewer_id: str
    ) -> NotifyResult:
        return await self.send(
            user_id=reviewer_id,
            message_type="pending_review",
            title="内容待审核",
            content=f"新内容「{content_title}」已生成，请审核。",
            channel="in_app",
        )

    async def send_publish_success(
        self, content_title: str, platform: str, publisher_id: str
    ) -> NotifyResult:
        return await self.send(
            user_id=publisher_id,
            message_type="publish_success",
            title="发布成功",
            content=f"内容「{content_title}」已成功发布到{platform}。",
            channel="in_app",
        )

    async def send_lead_alert(self, customer_name: str, dealer_id: str) -> NotifyResult:
        return await self.send(
            user_id=dealer_id,
            message_type="lead_alert",
            title="新线索提醒",
            content=f"收到新客户「{customer_name}」的咨询，请1小时内联系。",
            channel="wecom",
        )

    async def send_risk_alert(
        self, content_title: str, risk_words: list[str], operator_id: str
    ) -> NotifyResult:
        return await self.send(
            user_id=operator_id,
            message_type="risk_alert",
            title="风险词提醒",
            content=f"内容「{content_title}」包含风险词：{', '.join(risk_words)}，请检查。",
            channel="in_app",
        )


class EmailNotifyProvider:
    """邮件通知 Provider，通过 smtplib 发送。

    SMTP 配置优先读取 settings，缺失时用 os.getenv 兜底：
    SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / SMTP_FROM / SMTP_USE_SSL
    """

    def __init__(self):
        self.smtp_host = getattr(settings, "SMTP_HOST", None) or os.getenv(
            "SMTP_HOST", ""
        )
        self.smtp_port = int(
            getattr(settings, "SMTP_PORT", None) or os.getenv("SMTP_PORT", "465")
        )
        self.smtp_user = getattr(settings, "SMTP_USER", None) or os.getenv(
            "SMTP_USER", ""
        )
        self.smtp_pass = getattr(settings, "SMTP_PASS", None) or os.getenv(
            "SMTP_PASS", ""
        )
        self.smtp_from = (
            getattr(settings, "SMTP_FROM", None)
            or os.getenv("SMTP_FROM", "")
            or self.smtp_user
        )
        self.use_ssl = str(
            getattr(settings, "SMTP_USE_SSL", None) or os.getenv("SMTP_USE_SSL", "true")
        ).lower() in ("1", "true", "yes")

    def _send_mail(self, to_addr: str, subject: str, body: str) -> None:
        if not self.smtp_host or not self.smtp_user:
            raise RuntimeError("SMTP 配置不完整：缺少 SMTP_HOST/SMTP_USER")

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self.smtp_from
        msg["To"] = to_addr

        if self.use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                self.smtp_host, self.smtp_port, context=context, timeout=15
            ) as server:
                server.login(self.smtp_user, self.smtp_pass)
                server.sendmail(self.smtp_from, [to_addr], msg.as_string())
        else:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.login(self.smtp_user, self.smtp_pass)
                server.sendmail(self.smtp_from, [to_addr], msg.as_string())

    async def send(
        self,
        user_id: str,
        message_type: str,
        title: str,
        content: str,
        channel: str = "email",
    ) -> NotifyResult:
        message_id = f"notify_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        logger.info(
            "EmailNotifyProvider.send to=%s type=%s title=%s",
            user_id,
            message_type,
            title,
        )
        # user_id 作为收件邮箱地址
        try:
            self._send_mail(user_id, title, content)
            return NotifyResult(
                success=True,
                channel=channel,
                message_id=message_id,
                sent_at=now,
            )
        except Exception as e:
            logger.exception("EmailNotifyProvider 发送失败: %s", e)
            return NotifyResult(
                success=False,
                channel=channel,
                message_id=message_id,
                sent_at=now,
                error_message=str(e),
            )

    async def send_pending_review(
        self, content_title: str, reviewer_id: str
    ) -> NotifyResult:
        return await self.send(
            user_id=reviewer_id,
            message_type="pending_review",
            title="内容待审核",
            content=f"新内容「{content_title}」已生成，请审核。",
            channel="email",
        )

    async def send_publish_success(
        self, content_title: str, platform: str, publisher_id: str
    ) -> NotifyResult:
        return await self.send(
            user_id=publisher_id,
            message_type="publish_success",
            title="发布成功",
            content=f"内容「{content_title}」已成功发布到{platform}。",
            channel="email",
        )

    async def send_lead_alert(self, customer_name: str, dealer_id: str) -> NotifyResult:
        return await self.send(
            user_id=dealer_id,
            message_type="lead_alert",
            title="新线索提醒",
            content=f"收到新客户「{customer_name}」的咨询，请1小时内联系。",
            channel="email",
        )

    async def send_risk_alert(
        self, content_title: str, risk_words: list[str], operator_id: str
    ) -> NotifyResult:
        return await self.send(
            user_id=operator_id,
            message_type="risk_alert",
            title="风险词提醒",
            content=f"内容「{content_title}」包含风险词：{', '.join(risk_words)}，请检查。",
            channel="email",
        )


def get_notify_provider() -> (
    DisabledNotifyProvider
    | MockNotifyProvider
    | WeComNotifyProvider
    | EmailNotifyProvider
):
    provider = settings.NOTIFY_PROVIDER
    if provider == "disabled":
        return DisabledNotifyProvider()
    if provider == "mock":
        return MockNotifyProvider()
    if provider == "wecom":
        return WeComNotifyProvider()
    if provider == "email":
        return EmailNotifyProvider()
    raise NotImplementedError(f"Notify provider '{provider}' not implemented.")
