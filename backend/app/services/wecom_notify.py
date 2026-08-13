import logging
import time
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.lead import Lead, LeadFollowup
from app.utils.encryption import mask_phone

logger = logging.getLogger(__name__)
settings = get_settings()

WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"

# 模块级 access_token 缓存：{"token": str, "expires_at": float(timestamp)}
_access_token_cache: dict = {"token": "", "expires_at": 0}


def _wecom_configured() -> bool:
    return bool(settings.WECOM_CORP_ID and settings.WECOM_SECRET)


async def _get_access_token() -> str:
    """获取企微 access_token，带模块级缓存（过期前5分钟重新获取）。"""
    now = time.time()
    cached_token = _access_token_cache["token"]
    if cached_token and _access_token_cache["expires_at"] - now > 300:
        return cached_token

    url = f"{WECOM_API_BASE}/gettoken"
    params = {"corpid": settings.WECOM_CORP_ID, "corpsecret": settings.WECOM_SECRET}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
        data = resp.json()

    if data.get("errcode", 0) != 0 or "access_token" not in data:
        errcode = data.get("errcode", -1)
        errmsg = data.get("errmsg", "unknown")
        logger.error("获取企微 access_token 失败 errcode=%s errmsg=%s", errcode, errmsg)
        raise RuntimeError(
            f"获取企微 access_token 失败: errcode={errcode}, errmsg={errmsg}"
        )

    _access_token_cache["token"] = data["access_token"]
    _access_token_cache["expires_at"] = now + int(data.get("expires_in", 7200))
    logger.info("企微 access_token 已刷新，有效期 %s 秒", data.get("expires_in", 7200))
    return _access_token_cache["token"]


@dataclass
class WeComMessage:
    sender_id: str
    sender_name: str
    content: str


class WeComNotifyService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def send(self, user_id: str, message: str) -> dict:
        logger.info("WeCom send to %s: %s", user_id, message)

        if not _wecom_configured():
            raise RuntimeError("企业微信未配置，无法发送通知")

        try:
            token = await _get_access_token()
            url = f"{WECOM_API_BASE}/message/send"
            payload = {
                "touser": user_id,
                "msgtype": "text",
                "agentid": int(settings.WECOM_AGENT_ID),
                "text": {"content": message},
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url, params={"access_token": token}, json=payload
                )
                data = resp.json()
            logger.info(
                "WeCom message/send resp user_id=%s errcode=%s errmsg=%s",
                user_id,
                data.get("errcode"),
                data.get("errmsg"),
            )
            return data
        except Exception as e:
            logger.exception("WeCom send 调用失败: %s", e)
            return {"errcode": -1, "errmsg": str(e)}

    async def send_lead_notification(self, dealer_wecom_id: str, lead: Lead) -> dict:
        from app.utils.encryption import decrypt_phone

        try:
            phone = mask_phone(decrypt_phone(lead.customer_phone))
        except Exception:
            phone = "****"
        message = (
            f"【新线索通知】\n"
            f"客户：{lead.customer_name}\n"
            f"电话：{phone}\n"
            f"需求：{lead.requirement or '暂无'}\n"
            f"请1小时内联系客户！"
        )
        return await self.send(dealer_wecom_id, message)

    async def send_remind(
        self, user_id: str, content_title: str, scheduled_time: str
    ) -> dict:
        message = f"【发布提醒】\n内容：{content_title}\n计划时间：{scheduled_time}\n请手动发布到平台。"
        return await self.send(user_id, message)

    async def send_report(self, user_id: str, report_data: dict) -> dict:
        message = f"【运营周报】\n{report_data}"
        return await self.send(user_id, message)

    async def sync_contacts(self) -> list[dict]:
        if not _wecom_configured():
            logger.warning("企业微信未配置，通讯录返回空列表")
            return []

        try:
            token = await _get_access_token()
            url = f"{WECOM_API_BASE}/user/simplelist"
            params = {"access_token": token, "department_id": 1, "fetch_child": 1}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                data = resp.json()

            if data.get("errcode", 0) != 0:
                logger.error(
                    "sync_contacts 调用失败 errcode=%s errmsg=%s",
                    data.get("errcode"),
                    data.get("errmsg"),
                )
                return []

            contacts: list[dict] = []
            for u in data.get("userlist", []):
                contacts.append(
                    {
                        "userid": u.get("userid", ""),
                        "name": u.get("name", ""),
                        "department": u.get("department", []),
                        "mobile": u.get("mobile", ""),
                        "position": u.get("position", ""),
                    }
                )
            logger.info("sync_contacts 成功获取 %d 个联系人", len(contacts))
            return contacts
        except Exception as e:
            logger.exception("sync_contacts 调用失败: %s", e)
            return []


class WeComKeywordHandler:
    KEYWORD_MAP = {
        "已联系": "contacted",
        "已预约": "appointment_measured",
        "已量房": "measured",
        "已报价": "quoted",
        "已签单": "signed",
        "已流失": "lost",
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self.wecom = WeComNotifyService(db)
        from app.services.lead_distribute import LeadDistributionService

        self.lead_service = LeadDistributionService(db)

    def match_keyword(self, content: str) -> str | None:
        for keyword, status in self.KEYWORD_MAP.items():
            if keyword in content:
                return status
        return None

    async def handle_message(self, msg: WeComMessage) -> dict | None:
        status = self.match_keyword(msg.content)
        if not status:
            return None

        lead = await self.lead_service.find_latest_pending(msg.sender_id)
        if not lead:
            await self.wecom.send(msg.sender_id, "未找到待跟进的线索")
            return {"handled": False}

        lead.status = status
        followup = LeadFollowup(
            lead_id=lead.id,
            operator=msg.sender_name,
            action=status,
            note=msg.content,
        )
        self.db.add(followup)
        await self.db.commit()

        if status == "signed":
            await self.wecom.send(msg.sender_id, "请回复签单金额，如：签单2.5万")

        await self.wecom.send(
            msg.sender_id, f"✅ 线索状态已更新：{lead.customer_name} → {status}"
        )
        return {"handled": True, "lead_id": str(lead.id), "status": status}
