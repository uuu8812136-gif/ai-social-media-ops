import base64
import hashlib
import hmac
import logging

from defusedxml import ElementTree as ET
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import require_roles
from app.models.lead import Lead
from app.models.user import User
from app.schemas.common import (
    WeComCallbackRequest,
    WeComSendLeadRequest,
    WeComSendRemindRequest,
    WeComSendReportRequest,
)
from app.services.wecom_notify import (
    WeComKeywordHandler,
    WeComMessage,
    WeComNotifyService,
)
from app.utils.response import success

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/wecom", tags=["wecom"])


def verify_wecom_signature(
    token: str, timestamp: str, nonce: str, encrypt: str, msg_signature: str
) -> None:
    """企微回调签名校验。

    算法：sha1(sort([token, timestamp, nonce, encrypt]).join(""))，与 msg_signature 比较。
    校验失败抛 HTTPException(401)。
    """
    parts = sorted([token, timestamp, nonce, encrypt])
    # 企业微信协议固定使用 SHA-1；此处不是自行设计密码学方案。
    computed = hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()  # nosec B324
    if not hmac.compare_digest(computed, msg_signature):
        logger.warning("企微签名校验失败")
        raise HTTPException(status_code=401, detail="签名校验失败")


def decrypt_wecom_message(encrypt: str, encoding_aes_key: str) -> dict:
    """解密企微回调消息。

    AES-CBC-256 解密：key = base64decode(encoding_aes_key + "=")，iv = key[:16]。
    解密后去掉 PKCS#7 填充，再去除 16 字节随机串前缀，解析 4 字节消息长度 + 消息体 XML。
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    try:
        key = base64.b64decode(encoding_aes_key + "=", validate=True)
        ciphertext = base64.b64decode(encrypt, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="企微加密消息格式错误") from exc
    if len(key) != 32 or not ciphertext or len(ciphertext) % 16:
        raise HTTPException(status_code=400, detail="企微加密参数长度错误")

    iv = key[:16]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    raw = decryptor.update(ciphertext) + decryptor.finalize()
    decrypted = _pkcs7_unpad(raw)

    # decrypted 结构：16字节随机串 + 4字节消息长度(大端) + 消息XML + ReceiveId
    if len(decrypted) < 20:
        raise HTTPException(status_code=400, detail="企微加密消息长度错误")
    msg_len = int.from_bytes(decrypted[16:20], byteorder="big")
    msg_end = 20 + msg_len
    if msg_len <= 0 or msg_end > len(decrypted) or msg_len > 1024 * 1024:
        raise HTTPException(status_code=400, detail="企微消息正文长度错误")
    try:
        msg_xml = decrypted[20:msg_end].decode("utf-8")
        receive_id = decrypted[msg_end:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="企微消息编码错误") from exc

    try:
        root = ET.fromstring(msg_xml)
    except ET.ParseError as exc:
        raise HTTPException(status_code=400, detail="企微消息 XML 格式错误") from exc
    return {
        "to_user": root.findtext("ToUserName", "") or "",
        "from_user": root.findtext("FromUserName", "") or "",
        "create_time": root.findtext("CreateTime", "") or "",
        "msg_type": root.findtext("MsgType", "") or "",
        "content": root.findtext("Content", "") or "",
        "msg_id": root.findtext("MsgId", "") or "",
        "receive_id": receive_id,
    }


def _pkcs7_unpad(data: bytes) -> bytes:
    """去除 PKCS#7 填充。"""
    if not data:
        raise HTTPException(status_code=400, detail="企微消息解密结果为空")
    pad_len = data[-1]
    if pad_len < 1 or pad_len > 32:
        raise HTTPException(status_code=400, detail="企微消息填充错误")
    if data[-pad_len:] != bytes([pad_len]) * pad_len:
        raise HTTPException(status_code=400, detail="企微消息填充错误")
    return data[:-pad_len]


@router.post("/callback")
async def wecom_callback(
    body: WeComCallbackRequest, db: AsyncSession = Depends(get_db)
):
    handler = WeComKeywordHandler(db)

    # 加密模式：企微真实回调带有 msg_signature/encrypt 字段
    encrypted_fields = [body.encrypt, body.msg_signature, body.timestamp, body.nonce]
    if any(encrypted_fields) and not all(encrypted_fields):
        raise HTTPException(status_code=400, detail="企微加密回调参数不完整")
    if all(encrypted_fields):
        if not settings.WECOM_TOKEN or not settings.WECOM_ENCODING_AES_KEY:
            raise HTTPException(status_code=503, detail="企业微信回调尚未配置")
        verify_wecom_signature(
            token=settings.WECOM_TOKEN,
            timestamp=body.timestamp or "",
            nonce=body.nonce or "",
            encrypt=body.encrypt,
            msg_signature=body.msg_signature,
        )
        decrypted = decrypt_wecom_message(body.encrypt, settings.WECOM_ENCODING_AES_KEY)
        receive_id = decrypted.get("receive_id", "")
        if (
            settings.WECOM_CORP_ID
            and receive_id
            and not hmac.compare_digest(receive_id, settings.WECOM_CORP_ID)
        ):
            logger.warning("企微回调 ReceiveId 不匹配")
            raise HTTPException(status_code=401, detail="回调接收方校验失败")
        sender_id = decrypted.get("from_user", "")
        content = decrypted.get("content", "")
        sender_name = "经销商"
    else:
        if settings.is_production:
            raise HTTPException(
                status_code=401, detail="生产环境仅接受加密签名的企业微信回调"
            )
        # 仅开发测试模式允许明文字段。
        sender_id = body.sender_id
        content = body.content
        sender_name = body.sender_name

    msg = WeComMessage(sender_id=sender_id, sender_name=sender_name, content=content)
    result = await handler.handle_message(msg)
    if result is None:
        return success({"handled": False, "message": "非关键词消息，已忽略"})
    return success(result)


@router.post("/send/lead")
async def send_lead(
    body: WeComSendLeadRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    result = await db.execute(select(Lead).where(Lead.id == body.lead_id))
    lead = result.scalar_one_or_none()
    if not lead or not lead.assigned_dealer_id:
        return success({"sent": False, "message": "线索不存在或未分配"})
    from app.models.dealer import Dealer

    dealer_result = await db.execute(
        select(Dealer).where(Dealer.id == lead.assigned_dealer_id)
    )
    dealer = dealer_result.scalar_one_or_none()
    wecom = WeComNotifyService(db)
    resp = await wecom.send_lead_notification(dealer.wecom_id if dealer else "", lead)
    return success(resp)


@router.post("/send/remind")
async def send_remind(
    body: WeComSendRemindRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    wecom = WeComNotifyService(db)
    resp = await wecom.send_remind(
        body.user_id, body.content_title, body.scheduled_time
    )
    return success(resp)


@router.post("/send/report")
async def send_report(
    body: WeComSendReportRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    wecom = WeComNotifyService(db)
    data = body.report_data or {"type": body.report_type or "weekly"}
    resp = await wecom.send_report(body.user_id, data)
    return success(resp)


@router.get("/contacts")
async def sync_contacts(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
):
    wecom = WeComNotifyService(db)
    contacts = await wecom.sync_contacts()
    return success({"contacts": contacts})
