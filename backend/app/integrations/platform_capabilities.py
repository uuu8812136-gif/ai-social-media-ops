"""平台能力权威源（platform_capabilities）。

本模块是「哪些平台在发布 / 采集 / 扫码登录上真实可用」的唯一真相来源，
供后端 API 与前端展示统一消费，避免把未完成平台展示为「完整支持」。

发布定时能力说明：
- system_scheduled: 系统是否支持定时派发（Celery apply_async eta）
- native_scheduled: 平台是否支持平台内预约发布（尚未接入）

发布定时能力：system_scheduled=True 表示系统支持 Celery eta 定时派发；native_scheduled=False 表示平台内预约发布尚未接入。

能力状态分级（status）：
- verified: 已实测回归通过，可放心用于生产
- beta:     代码链路完整，但未在本仓库做平台级实测回归，使用需人工验收
- planned:  仅占位 / 未接入，前端应禁用并标注「待接入」

当前判定依据（2026-07）：
- 发布（synapse_engine.platforms.builtin.BuiltinPlatformAdapter）：
  五平台共用一套 Playwright 适配器，selector 来自原 Synapse，未做平台级回归 → beta
- 采集（mediacrawler_engine.embedded.factory）：
  xhs / dy / bili 有真实采集器（关键词搜索 MVP）→ beta；ks / wb → planned
- 扫码登录：五个发布平台均由 Synapse 支持二维码登录
"""

from __future__ import annotations

from typing import Any

VERIFIED = "verified"
BETA = "beta"
PLANNED = "planned"

STATUS_LABELS = {
    VERIFIED: "已验证可用",
    BETA: "可用(未实测)",
    PLANNED: "待接入",
}


# 规范平台注册表：canonical = 发布侧平台名（与 SocialAccount.platform / Synapse 一致）
# crawl_code = 采集侧短代码（MediaCrawler 使用）；None 表示采集模块未涵盖该平台
_PLATFORMS: list[dict[str, Any]] = [
    {
        "platform": "xiaohongshu",
        "name": "小红书",
        "code": 1,
        "crawl_code": "xhs",
        "aliases": ["xhs", "红书"],
        "publish": {
            "status": BETA,
            "needs_login": True,
            "system_scheduled": True,
            "native_scheduled": False,
        },
        "crawl": {"status": BETA, "modes": ["search"]},
        "login": {"qrcode": True},
        "acceptance": {
            "login": BETA,
            "publish": BETA,
            "human_verification": BETA,
            "success_reconciliation": BETA,
            "requires_live_account_check": True,
        },
    },
    {
        "platform": "channels",
        "name": "视频号",
        "code": 2,
        "crawl_code": None,
        "aliases": ["weixin_video", "wechat_video", "视频号"],
        "publish": {
            "status": BETA,
            "needs_login": True,
            "system_scheduled": True,
            "native_scheduled": False,
        },
        "crawl": {"status": PLANNED, "modes": []},
        "login": {"qrcode": True},
        "acceptance": {
            "login": BETA,
            "publish": BETA,
            "human_verification": BETA,
            "success_reconciliation": BETA,
            "requires_live_account_check": True,
        },
    },
    {
        "platform": "douyin",
        "name": "抖音",
        "code": 3,
        "crawl_code": "dy",
        "aliases": ["dy", "抖音"],
        "publish": {
            "status": BETA,
            "needs_login": True,
            "system_scheduled": True,
            "native_scheduled": False,
        },
        "crawl": {"status": BETA, "modes": ["search"]},
        "login": {"qrcode": True},
        "acceptance": {
            "login": BETA,
            "publish": BETA,
            "human_verification": BETA,
            "success_reconciliation": BETA,
            "requires_live_account_check": True,
        },
    },
    {
        "platform": "kuaishou",
        "name": "快手",
        "code": 4,
        "crawl_code": "ks",
        "aliases": ["ks", "快手"],
        "publish": {
            "status": BETA,
            "needs_login": True,
            "system_scheduled": True,
            "native_scheduled": False,
        },
        "crawl": {"status": PLANNED, "modes": []},
        "login": {"qrcode": True},
        "acceptance": {
            "login": BETA,
            "publish": BETA,
            "human_verification": BETA,
            "success_reconciliation": BETA,
            "requires_live_account_check": True,
        },
    },
    {
        "platform": "bilibili",
        "name": "B站",
        "code": 5,
        "crawl_code": "bili",
        "aliases": ["bili", "b站", "哔哩哔哩"],
        "publish": {
            "status": BETA,
            "needs_login": True,
            "system_scheduled": True,
            "native_scheduled": False,
        },
        "crawl": {"status": BETA, "modes": ["search"]},
        "login": {"qrcode": True},
        "acceptance": {
            "login": BETA,
            "publish": BETA,
            "human_verification": BETA,
            "success_reconciliation": BETA,
            "requires_live_account_check": True,
        },
    },
    {
        "platform": "weibo",
        "name": "微博",
        "code": None,
        "crawl_code": "wb",
        "aliases": ["wb", "微博"],
        "publish": {
            "status": PLANNED,
            "needs_login": True,
            "system_scheduled": True,
            "native_scheduled": False,
        },
        "crawl": {"status": PLANNED, "modes": []},
        "login": {"qrcode": False},
        "acceptance": {
            "login": PLANNED,
            "publish": PLANNED,
            "human_verification": PLANNED,
            "success_reconciliation": PLANNED,
            "requires_live_account_check": True,
        },
    },
]


def _with_labels(entry: dict[str, Any]) -> dict[str, Any]:
    """给能力项补充人类可读的状态标签，避免前端各自硬编码。"""
    out = {
        "platform": entry["platform"],
        "name": entry["name"],
        "code": entry["code"],
        "crawl_code": entry["crawl_code"],
        "aliases": entry["aliases"],
        "publish": {
            **entry["publish"],
            "status_label": STATUS_LABELS.get(
                entry["publish"]["status"], entry["publish"]["status"]
            ),
            "available": entry["publish"]["status"] in (VERIFIED, BETA),
        },
        "crawl": {
            **entry["crawl"],
            "status_label": STATUS_LABELS.get(
                entry["crawl"]["status"], entry["crawl"]["status"]
            ),
            "available": entry["crawl"]["status"] in (VERIFIED, BETA),
        },
        "login": entry["login"],
        "acceptance": {
            **entry["acceptance"],
            "status_labels": {
                key: STATUS_LABELS.get(value, value)
                for key, value in entry["acceptance"].items()
                if key != "requires_live_account_check"
            },
        },
    }
    return out


def all_capabilities() -> list[dict[str, Any]]:
    """返回全部平台能力（含状态标签），供统一能力接口使用。"""
    return [_with_labels(e) for e in _PLATFORMS]


def publish_platforms() -> list[dict[str, Any]]:
    """返回支持发布 / 扫码登录的平台（publish 非 planned）。"""
    return [_with_labels(e) for e in _PLATFORMS if e["publish"]["status"] != PLANNED]


def crawl_platforms() -> list[dict[str, Any]]:
    """返回采集侧平台（以采集短代码 platform 字段暴露，兼容既有前端）。"""
    result: list[dict[str, Any]] = []
    for e in _PLATFORMS:
        if not e["crawl_code"]:
            continue
        result.append(
            {
                "platform": e["crawl_code"],
                "name": e["name"],
                "alias": e["platform"],
                "crawler_available": e["crawl"]["status"] in (VERIFIED, BETA),
                "status": e["crawl"]["status"],
                "status_label": STATUS_LABELS.get(
                    e["crawl"]["status"], e["crawl"]["status"]
                ),
                "modes": e["crawl"]["modes"],
            }
        )
    return result


def normalize_platform(name: str) -> str | None:
    """把任意平台别名（含视频号的多种写法、采集短码）规范化为 canonical 平台名。"""
    if not name:
        return None
    key = name.strip().lower()
    for e in _PLATFORMS:
        if key == e["platform"]:
            return e["platform"]
        if e["crawl_code"] and key == e["crawl_code"]:
            return e["platform"]
        if key in [a.lower() for a in e["aliases"]]:
            return e["platform"]
    return None


def publish_status(platform: str) -> str:
    """返回某平台的发布能力状态；未知平台按 planned 处理。"""
    canonical = normalize_platform(platform)
    for e in _PLATFORMS:
        if e["platform"] == canonical:
            return e["publish"]["status"]
    return PLANNED


__all__ = [
    "VERIFIED",
    "BETA",
    "PLANNED",
    "STATUS_LABELS",
    "all_capabilities",
    "publish_platforms",
    "crawl_platforms",
    "normalize_platform",
    "publish_status",
]
