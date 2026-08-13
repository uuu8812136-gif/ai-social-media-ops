"""发布验证码 / 人机验证协调管理器。

职责：
- worker 检测到短信、滑块或安全验证时，暂停发布流程，写库标记任务状态，
  并显示正在执行发布的 Mac 宿主真实 Chrome 供用户操作。
- 前端通过 API（social_publish.py）调用 submit_captcha / resume / dismiss 推送信号。

native_host 模式下站内不展示网页、验证码输入框或 noVNC。用户在真实官网窗口
完成验证后，worker 自动检测验证控件消失并继续。旧 worker/noVNC 元数据仅保留
为兼容历史部署。
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.social_account import PublishTask, SocialAccount

logger = logging.getLogger(__name__)


# ===== 自定义异常 =====
class VerificationError(Exception):
    """验证流程通用错误。"""


class VerificationTimeout(VerificationError):
    """等待用户输入/操作超时。"""


class VerificationDismissed(VerificationError):
    """用户点了"忽略"，主动放弃验证。"""


# ===== 任务上下文 contextvar =====
# worker（workers/tasks.py）在执行发布任务前 set_current_task_id(task_id)，
# builtin.py 内部通过 get_current_task_id() 读取，无需改动 service/publisher 签名。
_current_task_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "synapse_current_task_id", default=None
)


def set_current_task_id(task_id: str | None) -> contextvars.ContextToken:
    """设置当前 worker 协程绑定的发布任务 ID，返回 reset token。"""
    return _current_task_id.set(task_id or None)


def reset_current_task_id(token: contextvars.ContextToken) -> None:
    """重置当前协程的 task_id（配合 set_current_task_id 返回的 token）。"""
    try:
        _current_task_id.reset(token)
    except Exception:
        pass


def get_current_task_id() -> str | None:
    """获取当前协程绑定的发布任务 ID（builtin.py 内部使用）。"""
    return _current_task_id.get()


def normalize_verification_type(raw_type: str | None, status: str | None) -> str:
    """统一历史 phone/human 与当前前端使用的规范验证类型。"""
    if raw_type in {"phone", "phone_captcha"}:
        return "phone_captcha"
    if raw_type in {"human", "human_captcha"}:
        return "human_captcha"
    if status == "needs_human_captcha":
        return "human_captcha"
    return "phone_captcha"


class VncSessionInfo:
    """browser-vnc 远程会话信息（人机验证场景）。"""

    def __init__(
        self,
        session_id: str,
        cdp_url: str,
        vnc_password: str,
        display: str = "",
    ) -> None:
        self.session_id = session_id
        self.cdp_url = cdp_url
        self.vnc_password = vnc_password
        self.display = display

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "cdp_url": self.cdp_url,
            "vnc_password": self.vnc_password,
            "display": self.display,
        }


class VerificationManager:
    """验证码 / 人机验证协调管理器（单例）。"""

    def __init__(self) -> None:
        self.settings = get_settings()

    # ===== Redis 连接（与 token_store 用法对齐：REDIS_URL 已含密码）=====
    def _redis(self) -> Redis:
        return Redis.from_url(
            self.settings.REDIS_URL,
            socket_connect_timeout=3,
            socket_timeout=3,
            decode_responses=True,
        )

    def _channel(self, task_id: str) -> str:
        prefix = self.settings.SYNAPSE_VERIFICATION_REDIS_PREFIX or "synapse:verify"
        return f"{prefix}:task:{task_id}"

    # ===== 截图存储 =====
    def _save_screenshot(
        self, platform: str, task_id: str, data: bytes
    ) -> str | None:
        """保存验证弹窗截图到 SYNAPSE_STORAGE_DIR/screenshots/<platform>/verification/。

        返回相对 SYNAPSE_STORAGE_DIR 的路径（便于前端拼接展示）。
        """
        if not data:
            return None
        try:
            base = (
                Path(self.settings.SYNAPSE_STORAGE_DIR)
                / "screenshots"
                / platform
                / "verification"
            )
            base.mkdir(parents=True, exist_ok=True)
            ts = int(time.time() * 1000)
            path = base / f"{task_id}_{ts}.png"
            path.write_bytes(data)
            try:
                return str(path.relative_to(Path(self.settings.SYNAPSE_STORAGE_DIR)))
            except Exception:
                return str(path)
        except Exception as exc:
            logger.warning("[verification] 保存截图失败 task=%s: %s", task_id, exc)
            return None

    async def get_screenshot_path(self, task_id: str) -> Path | None:
        """返回任务验证截图的安全绝对路径，不允许越出存储目录。"""
        task = await self._get_task(task_id)
        if task is None:
            return None
        raw_path = str((task.verification_meta or {}).get("screenshot_path") or "")
        if not raw_path:
            return None

        storage_root = Path(self.settings.SYNAPSE_STORAGE_DIR).resolve()
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = storage_root / candidate
        try:
            resolved = candidate.resolve()
            resolved.relative_to(storage_root)
        except (OSError, ValueError):
            logger.warning(
                "[verification] 拒绝存储目录外的截图路径 task=%s path=%s",
                task_id,
                raw_path,
            )
            return None
        return resolved if resolved.is_file() else None

    # ===== DB 读写 =====
    async def _set_task_status(
        self,
        task_id: str,
        status: str,
        verification_meta_patch: dict | None = None,
    ) -> PublishTask | None:
        """更新 PublishTask 状态并合并 verification_meta。"""
        try:
            tid = uuid.UUID(str(task_id))
        except (ValueError, TypeError):
            logger.warning("[verification] task_id 非法: %s", task_id)
            return None
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(PublishTask).where(PublishTask.id == tid))
            task = res.scalar_one_or_none()
            if task is None:
                logger.warning("[verification] PublishTask %s 不存在", task_id)
                return None
            task.status = status
            if verification_meta_patch:
                existing = dict(task.verification_meta or {})
                existing.update(verification_meta_patch)
                task.verification_meta = existing
            await db.commit()
            return task

    async def _get_task(self, task_id: str) -> PublishTask | None:
        try:
            tid = uuid.UUID(str(task_id))
        except (ValueError, TypeError):
            return None
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(PublishTask).where(PublishTask.id == tid))
            return res.scalar_one_or_none()

    # ===== Redis pub/sub 等待 / 发布 =====
    async def _wait_for_event(
        self, task_id: str, expected_events: set[str], timeout: int
    ) -> dict:
        """订阅 {prefix}:task:{task_id} 频道，阻塞等待指定事件，返回消息体 dict。

        用 pubsub.get_message(timeout=...) 循环，不做 sleep 轮询。
        超时抛 VerificationTimeout。
        """
        channel = self._channel(task_id)
        client = self._redis()
        pubsub = client.pubsub()
        deadline = time.time() + timeout
        try:
            await pubsub.subscribe(channel)
            logger.info(
                "[verification] 订阅 %s 等待事件 %s timeout=%ds",
                channel, expected_events, timeout,
            )
            while time.time() < deadline:
                remaining = max(1.0, deadline - time.time())
                msg = await pubsub.get_message(
                    timeout=min(remaining, 5.0),
                    ignore_subscribe_messages=True,
                )
                if msg is None:
                    continue
                if msg.get("type") != "message":
                    continue
                raw = msg.get("data")
                try:
                    payload = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    payload = {"event": str(raw)}
                if not isinstance(payload, dict):
                    continue
                event = str(payload.get("event") or "")
                if event in expected_events:
                    logger.info(
                        "[verification] 收到事件 %s on %s", event, channel
                    )
                    return payload
                # 其它事件忽略，继续等
            raise VerificationTimeout(
                f"等待验证事件 {expected_events} 超时 task={task_id}"
            )
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                pass
            try:
                await pubsub.aclose()
            except Exception:
                pass
            try:
                await client.aclose()
            except Exception:
                pass

    async def _publish_event(self, task_id: str, payload: dict) -> None:
        channel = self._channel(task_id)
        client = self._redis()
        try:
            await client.publish(channel, json.dumps(payload, ensure_ascii=False))
            logger.info(
                "[verification] 发布事件 %s -> %s", payload.get("event"), channel
            )
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    # ===== browser-vnc session-manager =====
    async def acquire_vnc_session_from_manager(
        self, platform: str, account_id: str, task_id: str
    ) -> dict:
        """向 browser-vnc session-manager 申请一个远程浏览器会话。

        POST {SYNAPSE_VNC_SESSION_MANAGER_URL}/sessions
        body: {platform, account_id, task_id, ttl:600}
        return: {session_id, cdp_url, vnc_password, display}
        失败抛 VerificationError。
        """
        base = (self.settings.SYNAPSE_VNC_SESSION_MANAGER_URL or "").strip()
        if not base:
            base = "http://browser-vnc:9223"
        url = base.rstrip("/") + "/sessions"
        ttl = int(self.settings.SYNAPSE_HUMAN_CAPTCHA_WAIT_TIMEOUT or 600)
        body = {
            "platform": platform,
            "account_id": account_id or "anon",
            "task_id": task_id,
            "ttl": ttl,
        }
        logger.info("[verification] 申请 vnc 会话 url=%s body=%s", url, body)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=5.0)
            ) as cx:
                resp = await cx.post(url, json=body)
        except httpx.HTTPError as exc:
            raise VerificationError(
                f"连接 browser-vnc session-manager 失败: {exc}"
            ) from exc
        if resp.status_code >= 400:
            raise VerificationError(
                f"session-manager 返回 {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        if not data.get("session_id"):
            raise VerificationError(f"session-manager 返回缺 session_id: {data}")
        return data

    async def release_vnc_session(self, session_id: str) -> None:
        """销毁远程浏览器会话。DELETE {base}/sessions/{session_id}"""
        if not session_id:
            return
        base = (
            self.settings.SYNAPSE_VNC_SESSION_MANAGER_URL or ""
        ).strip() or "http://browser-vnc:9223"
        url = base.rstrip("/") + f"/sessions/{session_id}"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=3.0)
            ) as cx:
                await cx.delete(url)
            logger.info("[verification] 已释放 vnc 会话 %s", session_id)
        except Exception as exc:
            logger.warning(
                "[verification] 释放 vnc 会话失败 %s: %s", session_id, exc
            )

    async def heartbeat_vnc_session(self, session_id: str) -> bool:
        """续期 browser-vnc 会话，避免人工操作期间被空闲清理。"""
        if not session_id:
            return False
        base = (
            self.settings.SYNAPSE_VNC_SESSION_MANAGER_URL or ""
        ).strip() or "http://browser-vnc:9223"
        url = base.rstrip("/") + f"/sessions/{session_id}/heartbeat"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(5.0, connect=2.0)
            ) as cx:
                resp = await cx.post(url)
            return resp.status_code < 400
        except Exception as exc:
            logger.warning(
                "[verification] vnc 会话续期失败 %s: %s", session_id, exc
            )
            return False

    # ===== 手机验证码 =====
    async def request_phone_captcha(
        self,
        task_id: str,
        platform: str,
        account_id: str,
        hint: str,
        page_screenshot_bytes: bytes,
        sms_requested: bool = False,
        sms_request_state: str = "",
        validation_error: str = "",
    ) -> str:
        """worker 检测到手机验证码后调用：写库 + 存截图 + 发通知 + 阻塞等验证码。

        返回用户提交的验证码字符串。超时抛 VerificationTimeout，被 dismiss 抛
        VerificationDismissed。
        """
        screenshot_path = self._save_screenshot(
            platform, task_id, page_screenshot_bytes
        )
        appeared_at = datetime.now(timezone.utc).isoformat()
        meta = {
            "verification_type": "phone_captcha",
            "captcha_hint": hint or "",
            "screenshot_path": screenshot_path,
            "sms_requested": bool(sms_requested),
            "sms_request_state": sms_request_state or "",
            "captcha_validation_status": "awaiting_input",
            "captcha_validation_error": validation_error or "",
            "appeared_at": appeared_at,
        }
        await self._set_task_status(task_id, "needs_phone_captcha", meta)
        logger.info(
            "[verification] phone_captcha_required task=%s platform=%s hint=%s",
            task_id, platform, hint,
        )
        # 发通知（前端主要靠轮询 pending 列表，这里的事件供实时订阅用）
        try:
            await self._publish_event(
                task_id,
                {
                    "event": "phone_captcha_required",
                    "hint": hint or "",
                    "screenshot": screenshot_path,
                },
            )
        except Exception as exc:
            logger.warning(
                "[verification] 发 phone_captcha_required 通知失败: %s", exc
            )

        timeout = int(self.settings.SYNAPSE_PHONE_CAPTCHA_WAIT_TIMEOUT or 300)
        payload = await self._wait_for_event(
            task_id, {"captcha_submitted", "dismissed"}, timeout
        )
        event = str(payload.get("event") or "")
        if event == "dismissed":
            raise VerificationDismissed(f"用户忽略验证 task={task_id}")
        code = str(payload.get("code") or "")
        if not code:
            raise VerificationError(f"收到的验证码为空 task={task_id}")
        # 收到验证码后只标记为校验中；必须等平台页面明确接受后，API 才能向
        # 前端返回成功。否则前端会先关闭弹窗，旧验证页又被识别成一次新验证。
        await self._set_task_status(
            task_id,
            "running",
            {
                "resolved_code": code,
                "resolved_at": datetime.now(timezone.utc).isoformat(),
                "captcha_validation_status": "checking",
                "captcha_validation_error": "",
            },
        )
        return code

    async def wait_phone_captcha_retry(self, task_id: str) -> str:
        """验证码被平台拒绝后，保持同一验证会话等待用户重新提交。"""
        timeout = int(self.settings.SYNAPSE_PHONE_CAPTCHA_WAIT_TIMEOUT or 300)
        payload = await self._wait_for_event(
            task_id, {"captcha_submitted", "dismissed"}, timeout
        )
        if str(payload.get("event") or "") == "dismissed":
            raise VerificationDismissed(f"用户忽略验证 task={task_id}")
        code = str(payload.get("code") or "")
        if not code:
            raise VerificationError(f"收到的验证码为空 task={task_id}")
        await self._set_task_status(
            task_id,
            "running",
            {
                "resolved_code": code,
                "resolved_at": datetime.now(timezone.utc).isoformat(),
                "captcha_validation_status": "checking",
                "captcha_validation_error": "",
            },
        )
        return code

    async def complete_phone_captcha(
        self, task_id: str, *, accepted: bool, error: str = ""
    ) -> None:
        """写入平台对验证码的真实校验结果，供提交 API 与前端同步等待。"""
        await self._set_task_status(
            task_id,
            "running" if accepted else "needs_phone_captcha",
            {
                "captcha_validation_status": "accepted" if accepted else "invalid",
                "captcha_validation_error": "" if accepted else (error or "验证码不正确，请重新输入"),
                "validated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def wait_for_captcha_validation(
        self, task_id: str, timeout: float = 20.0
    ) -> dict:
        """等待 worker 在真实平台页面完成验证码校验。"""
        deadline = time.monotonic() + max(1.0, float(timeout))
        while time.monotonic() < deadline:
            task = await self._get_task(task_id)
            if task is None:
                raise VerificationError(f"发布任务不存在 task={task_id}")
            meta = dict(task.verification_meta or {})
            status = str(meta.get("captcha_validation_status") or "")
            if status == "accepted":
                return {"accepted": True, "error": ""}
            if status == "invalid":
                return {
                    "accepted": False,
                    "error": str(meta.get("captcha_validation_error") or "验证码不正确，请重新输入"),
                }
            if task.status not in {
                "needs_phone_captcha",
                "running",
            }:
                raise VerificationError(
                    str(task.error_message or "验证码校验任务已结束")
                )
            await asyncio.sleep(0.25)
        raise VerificationTimeout(f"等待平台校验验证码超时 task={task_id}")

    # ===== 人工验证（宿主真实窗口；兼容旧 worker 方案）=====
    async def request_human_captcha(
        self,
        task_id: str,
        platform: str,
        account_id: str,
        page_screenshot_bytes: bytes,
        native_session_id: str = "",
    ) -> VncSessionInfo:
        """检测到人工验证后写库，并等待页面自动恢复或兼容 resume 信号。"""
        if native_session_id:
            session_id = native_session_id
            vnc_password = ""
            novnc_url = ""
            display = ""
            scheme = "native_window"
        else:
            # 兼容显式选择 worker 模式的旧部署。
            vnc_password = (
                self.settings.SYNAPSE_VERIFICATION_WORKER_VNC_PASSWORD
                or "trae-vnc-2026"
            )
            session_id = str(task_id)
            novnc_url = (
                self.settings.SYNAPSE_VERIFICATION_WORKER_NOVNC_URL
                or "http://celery:6080"
            )
            display = ":99"
            scheme = "worker_shared"

        screenshot_path = self._save_screenshot(
            platform, task_id, page_screenshot_bytes
        )
        appeared_at = datetime.now(timezone.utc).isoformat()
        meta = {
            "verification_type": "human_captcha",
            "vnc_session_id": session_id,
            "vnc_password": vnc_password,
            "display": display,
            "novnc_url": novnc_url,
            "screenshot_path": screenshot_path,
            "appeared_at": appeared_at,
            "scheme": scheme,
            "presentation": (
                "native_window" if native_session_id else "legacy_novnc"
            ),
        }
        await self._set_task_status(task_id, "needs_human_captcha", meta)
        logger.info(
            "[verification] human_captcha_required task=%s platform=%s presentation=%s",
            task_id,
            platform,
            meta["presentation"],
        )
        try:
            await self._publish_event(
                task_id,
                {
                    "event": "human_captcha_required",
                    "session_id": session_id,
                    "novnc_url": novnc_url,
                    "screenshot": screenshot_path,
                },
            )
        except Exception as exc:
            logger.warning(
                "[verification] 发 human_captcha_required 通知失败: %s", exc
            )

        timeout = int(self.settings.SYNAPSE_HUMAN_CAPTCHA_WAIT_TIMEOUT or 600)
        payload = await self._wait_for_event(
            task_id, {"human_captcha_done", "dismissed"}, timeout
        )
        event = str(payload.get("event") or "")
        if event == "dismissed":
            raise VerificationDismissed(f"用户忽略验证 task={task_id}")
        # resume 信号：兼容旧客户端；native 模式通常由页面自动检测完成。
        await self._set_task_status(
            task_id,
            "running",
            {"resolved_at": datetime.now(timezone.utc).isoformat()},
        )
        return VncSessionInfo(
            session_id=session_id,
            cdp_url="",
            vnc_password=vnc_password,
            display=display,
        )

    async def complete_browser_verification(
        self, task_id: str, *, auto_detected: bool = False
    ) -> None:
        """结束真实浏览器验证状态。

        当 worker 在页面上直接识别到发布成功或验证控件消失时，不需要用户
        再点击一次“继续发布”；更新任务状态后发布流程自动恢复。
        """
        await self._set_task_status(
            task_id,
            "running",
            {
                "resolved_at": datetime.now(timezone.utc).isoformat(),
                "auto_resolved": bool(auto_detected),
            },
        )

    # ===== 前端调用的动作 =====
    async def submit_captcha(self, task_id: str, code: str) -> None:
        """前端提交手机验证码：往频道发 captcha_submitted。"""
        task = await self._get_task(task_id)
        if task is None:
            raise VerificationError(f"发布任务不存在 task={task_id}")
        if task.status != "needs_phone_captcha":
            raise VerificationError("当前任务已不再等待验证码，请关闭旧弹窗")
        await self._set_task_status(
            task_id,
            "needs_phone_captcha",
            {
                "captcha_validation_status": "submitted",
                "captcha_validation_error": "",
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await self._publish_event(
            task_id, {"event": "captcha_submitted", "code": str(code or "")}
        )

    async def resume(self, task_id: str) -> None:
        """前端点"继续发布"：往频道发 human_captcha_done。"""
        await self._publish_event(task_id, {"event": "human_captcha_done"})

    async def dismiss(self, task_id: str) -> None:
        """前端点"忽略"：往频道发 dismissed。"""
        await self._publish_event(task_id, {"event": "dismissed"})

    # ===== 查询 =====
    async def pending_verifications(self) -> list[dict]:
        """查询所有 needs_phone_captcha / needs_human_captcha 的任务。

        join SocialAccount 取 nickname，返回前端需要的字段。
        """
        if (
            self.settings.SYNAPSE_PUBLISH_BROWSER_MODE or "worker"
        ).strip().lower() == "native_host":
            # 原生窗口模式由 worker 直接把真实平台 Chrome 切到前台，
            # 不再向站内旧版验证铃铛/自动弹窗暴露待处理任务。这样即使
            # 浏览器仍缓存旧 SPA，也不会重新唤起 noVNC 对话框。
            return []
        async with AsyncSessionLocal() as db:
            res = await db.execute(
                select(PublishTask, SocialAccount.nickname)
                .outerjoin(
                    SocialAccount,
                    PublishTask.social_account_id == SocialAccount.id,
                )
                .where(
                    PublishTask.status.in_(
                        ("needs_phone_captcha", "needs_human_captcha")
                    )
                )
                .order_by(PublishTask.updated_at.desc())
            )
            rows = res.all()
        items: list[dict] = []
        for task, nickname in rows:
            meta = dict(task.verification_meta or {})
            verification_type = normalize_verification_type(
                str(meta.get("verification_type") or ""), task.status
            )
            items.append(
                {
                    "task_id": str(task.id),
                    "platform": task.platform,
                    "nickname": nickname or "",
                    "verification_type": verification_type,
                    "status": task.status,
                    "appeared_at": meta.get("appeared_at"),
                    "captcha_hint": meta.get("captcha_hint") or "",
                    "screenshot_url": (
                        f"/api/v1/social/publish/tasks/{task.id}/verification/screenshot"
                        if meta.get("screenshot_path")
                        else ""
                    ),
                    "sms_requested": bool(meta.get("sms_requested")),
                    "sms_request_state": meta.get("sms_request_state") or "",
                    "vnc_session_id": meta.get("vnc_session_id") or "",
                    "scheme": meta.get("scheme") or "",
                    "presentation": meta.get("presentation") or "",
                }
            )
        return items

    async def get_vnc_session(self, task_id: str) -> dict:
        """返回该任务的 {session_id, vnc_password, cdp_url, display}。

        从 PublishTask.verification_meta JSONB 读取。任务不存在或无人机验证则返回 {}。
        """
        task = await self._get_task(task_id)
        if task is None:
            return {}
        meta = dict(task.verification_meta or {})
        presentation = str(meta.get("presentation") or "")
        scheme = str(meta.get("scheme") or "")
        native_publish_mode = (
            self.settings.SYNAPSE_PUBLISH_BROWSER_MODE or "worker"
        ).strip().lower() == "native_host"
        if (
            native_publish_mode
            or presentation == "native_window"
            or scheme == "native_window"
        ):
            # 后端兜底：即使客户端仍缓存着旧版 SPA，也不能把原生 Chrome
            # session_id 当成 noVNC token，从而再次弹出失效的站内大窗口。
            return {
                "session_id": "",
                "vnc_password": "",
                "cdp_url": "",
                "display": "",
                "presentation": "native_window",
                "scheme": "native_window",
            }
        return {
            "session_id": meta.get("vnc_session_id") or "",
            "vnc_password": meta.get("vnc_password") or "",
            "cdp_url": meta.get("cdp_url") or "",
            "display": meta.get("display") or "",
            "presentation": presentation,
            "scheme": scheme,
        }


# 单例
verification_manager = VerificationManager()


__all__ = [
    "VerificationManager",
    "verification_manager",
    "VerificationError",
    "VerificationTimeout",
    "VerificationDismissed",
    "VncSessionInfo",
    "set_current_task_id",
    "reset_current_task_id",
    "get_current_task_id",
    "normalize_verification_type",
]
