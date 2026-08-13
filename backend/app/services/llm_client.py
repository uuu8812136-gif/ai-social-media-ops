import asyncio
import ipaddress
import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.llm_config import LLMProviderConfig
from app.utils.llm_json import extract_json_value
from app.utils.encryption import decrypt_secret

settings = get_settings()

_FAKE_IP_PROXY_NETWORK = ipaddress.ip_network("198.18.0.0/15")


class LLMError(RuntimeError):
    status_code = 502


class LLMConfigurationError(LLMError):
    status_code = 503


class LLMUpstreamError(LLMError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider_name: str
    protocol: str
    base_url: str
    model: str
    api_key: str
    timeout_seconds: int
    source: str = "environment"


def _unsafe_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def _allowed_fake_ip_dns(address: str) -> bool:
    """Allow proxy fake-IP DNS only for hostnames and only when explicitly enabled."""
    return (
        settings.LLM_ALLOW_FAKE_IP_DNS
        and ipaddress.ip_address(address) in _FAKE_IP_PROXY_NETWORK
    )


async def ensure_safe_llm_base_url(base_url: str) -> None:
    """Block custom LLM endpoints that could be used for server-side network probing."""
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LLMConfigurationError("模型 API 地址必须是有效的 http/https 地址。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LLMConfigurationError("模型 API 地址不能包含凭据、查询参数或锚点。")
    if settings.LLM_ALLOW_PRIVATE_BASE_URL:
        return

    hostname = parsed.hostname.lower()
    if (
        hostname == "localhost"
        or hostname.endswith(".local")
        or hostname == "host.docker.internal"
    ):
        raise LLMConfigurationError("模型 API 地址不能指向本机或内网。")

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if _unsafe_ip(str(literal_ip)):
            raise LLMConfigurationError("模型 API 地址不能指向本机或内网。")
        return

    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise LLMConfigurationError("模型 API 域名无法解析，请检查地址。") from exc

    resolved = {item[4][0] for item in addresses}
    if not resolved or any(
        _unsafe_ip(address) and not _allowed_fake_ip_dns(address)
        for address in resolved
    ):
        raise LLMConfigurationError("模型 API 地址解析到了本机或内网，已拒绝连接。")


class LLMClient:
    """DeepSeek/Qwen client with mock mode."""

    def __init__(
        self,
        db: AsyncSession | None = None,
        runtime_override: LLMRuntimeConfig | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.db = db
        self.runtime_override = runtime_override
        self.transport = transport
        self._resolved_config: LLMRuntimeConfig | None = None

    def environment_config(self) -> LLMRuntimeConfig:
        provider = settings.LLM_PROVIDER.strip().lower()
        if provider == "deepseek":
            return LLMRuntimeConfig(
                provider_name="DeepSeek",
                protocol="chat_completions",
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
                api_key=settings.DEEPSEEK_API_KEY,
                timeout_seconds=int(settings.LLM_TIMEOUT_SECONDS),
            )
        if provider == "qwen":
            return LLMRuntimeConfig(
                provider_name="通义千问",
                protocol="chat_completions",
                base_url=settings.QWEN_BASE_URL,
                model=settings.QWEN_MODEL,
                api_key=settings.QWEN_API_KEY,
                timeout_seconds=int(settings.LLM_TIMEOUT_SECONDS),
            )
        raise LLMConfigurationError(
            f"不支持的 LLM_PROVIDER={settings.LLM_PROVIDER!r}，请在模型配置页面设置自定义 API。"
        )

    async def _database_config(self) -> LLMRuntimeConfig | None:
        if self.db is None:
            return None
        result = await self.db.execute(
            select(LLMProviderConfig).where(
                LLMProviderConfig.config_key == "default",
                LLMProviderConfig.is_active.is_(True),
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        try:
            api_key = decrypt_secret(record.api_key_encrypted)
        except Exception as exc:
            raise LLMConfigurationError(
                "已保存的模型 API Key 无法解密，请在模型配置页面重新填写。"
            ) from exc
        return LLMRuntimeConfig(
            provider_name=record.provider_name,
            protocol=record.protocol,
            base_url=record.base_url,
            model=record.model,
            api_key=api_key,
            timeout_seconds=record.timeout_seconds,
            source="database",
        )

    async def resolve_config(self) -> LLMRuntimeConfig:
        if self._resolved_config is not None:
            return self._resolved_config
        config = (
            self.runtime_override
            or await self._database_config()
            or self.environment_config()
        )
        if not config.api_key:
            raise LLMConfigurationError(
                "AI 模型未配置：请由管理员进入“模型配置”填写 API 地址、模型和 API Key。"
            )
        await ensure_safe_llm_base_url(config.base_url)
        self._resolved_config = config
        return config

    async def get_model_name(self) -> str:
        return (await self.resolve_config()).model

    @staticmethod
    def _chat_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict)
                and item.get("type") in {"text", "output_text"}
            )
        return ""

    @classmethod
    def _parse_chat_results(cls, data: Any) -> list[str]:
        choices = data.get("choices") if isinstance(data, dict) else None
        return [
            text
            for choice in (choices or [])
            if isinstance(choice, dict)
            for text in [cls._chat_text(choice.get("message", {}).get("content"))]
            if text
        ]

    @classmethod
    def _parse_responses_text(cls, data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        if isinstance(data.get("output_text"), str):
            return data["output_text"]
        parts: list[str] = []
        for output in data.get("output") or []:
            if not isinstance(output, dict):
                continue
            for content in output.get("content") or []:
                if isinstance(content, dict) and content.get("type") in {
                    "output_text",
                    "text",
                }:
                    parts.append(str(content.get("text") or ""))
        return "".join(parts)

    async def _post_json(
        self,
        client: httpx.AsyncClient,
        config: LLMRuntimeConfig,
        path: str,
        payload: dict[str, Any],
    ) -> Any:
        response = await client.post(
            f"{config.base_url.rstrip('/')}/{path}",
            headers={"Authorization": f"Bearer {config.api_key}"},
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def generate(
        self,
        model: str | None = None,
        prompt: str = "",
        n: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> list[str]:
        scenario = settings.MOCK_SCENARIO

        # Scenario: error — 模拟 LLM 服务异常
        if scenario == "error" and settings.AI_MOCK_MODE:
            raise RuntimeError("模拟 LLM 服务异常：模型接口不可用")

        # Scenario: timeout — 模拟超时
        if scenario == "timeout" and settings.AI_MOCK_MODE:
            import asyncio

            await asyncio.sleep(0.1)
            raise TimeoutError("模拟 LLM 服务超时")

        # Scenario: empty — 返回空内容
        if scenario == "empty" and settings.AI_MOCK_MODE:
            return [""]

        if settings.AI_MOCK_MODE:
            return [self._mock_response(prompt, i) for i in range(n)]

        config = await self.resolve_config()
        resolved_model = model or config.model

        timeout = httpx.Timeout(
            config.timeout_seconds, connect=min(15.0, config.timeout_seconds)
        )
        try:
            async with httpx.AsyncClient(
                timeout=timeout, transport=self.transport
            ) as client:
                if config.protocol == "chat_completions":
                    payload = {
                        "model": resolved_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "n": n,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    parsed_base_url = urlsplit(config.base_url)
                    if (
                        parsed_base_url.hostname == "ark.cn-beijing.volces.com"
                        and "/api/coding/" in parsed_base_url.path
                    ):
                        # Coding Plan reasoning models can consume the full output
                        # budget before returning content unless thinking is disabled.
                        payload["thinking"] = {"type": "disabled"}
                    data = await self._post_json(
                        client,
                        config,
                        "chat/completions",
                        payload,
                    )
                    results = self._parse_chat_results(data)
                elif config.protocol == "responses":
                    results = []
                    for _ in range(n):
                        data = await self._post_json(
                            client,
                            config,
                            "responses",
                            {
                                "model": resolved_model,
                                "input": prompt,
                                "max_output_tokens": max_tokens,
                            },
                        )
                        text = self._parse_responses_text(data)
                        if text:
                            results.append(text)
                else:
                    raise LLMConfigurationError(f"不支持的模型协议：{config.protocol}")
        except httpx.TimeoutException as exc:
            raise LLMUpstreamError(
                f"{config.provider_name} 响应超时，请稍后重试。", status_code=504
            ) from exc
        except httpx.HTTPStatusError as exc:
            upstream_status = exc.response.status_code
            if upstream_status in {401, 403}:
                message = f"{config.provider_name} API Key 无效或没有模型权限。"
            elif upstream_status == 429:
                message = f"{config.provider_name} 请求过于频繁或额度不足，请稍后重试。"
            else:
                message = f"{config.provider_name} 服务调用失败（HTTP {upstream_status}），请稍后重试。"
            raise LLMUpstreamError(message) from exc
        except httpx.RequestError as exc:
            raise LLMUpstreamError(
                f"无法连接 {config.provider_name} 服务，请检查网络和模型地址。"
            ) from exc
        except (ValueError, TypeError) as exc:
            raise LLMUpstreamError(
                f"{config.provider_name} 返回了无法解析的数据。"
            ) from exc

        if not results:
            raise LLMUpstreamError(
                f"{config.provider_name} 未返回可用内容，请调整输入后重试。"
            )
        return results

    async def judge(self, content: str, issues: list[dict]) -> list[dict]:
        if settings.AI_MOCK_MODE:
            return []
        prompt = (
            "判断以下社媒内容是否还存在已知规则之外的高风险合规问题。"
            "只返回 JSON 数组，不要使用 Markdown；没有新增问题时返回 []。"
            "数组元素字段为 word、category、severity、suggestion。\n"
            f"已知问题：{json.dumps(issues, ensure_ascii=False)}\n内容：{content}"
        )
        result = await self.generate(
            prompt=prompt, n=1, temperature=0.1, max_tokens=500
        )
        parsed = extract_json_value(result[0]) if result else []
        return (
            [item for item in parsed if isinstance(item, dict)]
            if isinstance(parsed, list)
            else []
        )

    def _mock_response(self, prompt: str, index: int) -> str:
        """Enhanced mock response with city/platform/strategy-specific content."""
        import hashlib

        # Stable seed for predictable results
        seed = int(hashlib.sha256(prompt.encode()).hexdigest()[:8], 16) + index
        import random

        rng = random.Random(seed)

        # Detect content type and parameters from prompt
        is_script = "脚本" in prompt or "video_script" in prompt or "hook" in prompt
        is_localize = "本地化" in prompt or "localize" in prompt

        # Detect platform
        platform = "douyin"
        if "小红书" in prompt or "xiaohongshu" in prompt:
            platform = "xiaohongshu"
        elif "视频号" in prompt or "wechat_video" in prompt:
            platform = "wechat_video"
        elif "公众号" in prompt or "wechat_mp" in prompt:
            platform = "wechat_mp"

        # Detect topic
        topic = "门窗选购"
        for line in prompt.split("\n"):
            if "选题" in line or "topic" in line.lower():
                topic = line.split(":")[-1].strip()[:30] or "门窗选购"
                break

        # Detect cities
        cities = []
        for city in ["广州", "深圳", "北京", "佛山", "东莞"]:
            if city in prompt:
                cities.append(city)

        # Detect knowledge context
        has_knowledge = "知识库" in prompt or "knowledge" in prompt.lower()
        knowledge_references = []
        if has_knowledge:
            knowledge_references = [
                {
                    "document_id": "mock-doc-1",
                    "chunk_id": "mock-chunk-1",
                    "title": f"{topic}参考文档",
                    "source": "知识库",
                    "score": 8,
                },
                {
                    "document_id": "mock-doc-2",
                    "chunk_id": "mock-chunk-2",
                    "title": "门窗行业案例",
                    "source": "知识库",
                    "score": 6,
                },
            ]

        # Platform-specific content templates
        if is_script:
            hooks = {
                "douyin": [
                    "隔壁装修吵到崩溃？换个窗户试试",
                    "新房验收这3个门窗问题必须查",
                    "老小区窗户漏风？一招解决",
                ],
                "xiaohongshu": [
                    "装修小白必看！门窗选购避坑指南",
                    "实测！换完窗户家里安静了",
                    "封阳台到底选推拉还是平开？",
                ],
                "wechat_video": [
                    "门窗安装这3步不能省",
                    "旧窗改造全过程记录",
                    "断桥铝门窗怎么选不踩坑",
                ],
            }
            hook_list = hooks.get(platform, hooks["douyin"])
            hook = hook_list[rng.randint(0, len(hook_list) - 1)]

            bodies = {
                "douyin": f"今天帮客户家做{topic}实测，型材壁厚1.8mm，中空钢化玻璃，安装2天搞定。",
                "xiaohongshu": f"姐妹们！{topic}真的要重视，我家之前窗户漏风，换了断桥铝之后冬天暖和多了。",
                "wechat_video": f"很多业主问{topic}怎么选，关键是看型材壁厚、玻璃配置和安装工艺。",
            }
            body = bodies.get(platform, bodies["douyin"])

            ctas = [
                "评论区扣1，免费上门量房",
                "关注我，装修少走弯路",
                "私信预约免费测量",
            ]
            cta = ctas[rng.randint(0, len(ctas) - 1)]

            tags_pool = [
                "门窗选购",
                "装修避坑",
                "实测对比",
                "阳台封窗",
                "隔音实测",
                "断桥铝",
                "旧窗改造",
                "防盗门",
            ]
            tags = rng.sample(tags_pool, min(3, len(tags_pool)))

            localizations = {}
            for city in cities:
                city_content = {
                    "广州": f"广州{topic}案例：天河区张先生选用70系列断桥铝，5天完成安装",
                    "深圳": f"深圳{topic}案例：南山区李女士选用加强型断桥铝，抗风压设计",
                    "北京": f"北京{topic}案例：朝阳区王先生选用80系列+Low-E玻璃，冬季保温升级",
                    "佛山": f"佛山{topic}案例：禅城区黄先生选用断桥铝推拉窗，防潮密封升级",
                    "东莞": f"东莞{topic}案例：南城区何先生全屋更换断桥铝，4天完成",
                }
                localizations[city] = city_content.get(city, f"{city}本地化版本")

            result = {
                "title": f"{topic} - 版本{index + 1}",
                "hook": hook,
                "body": body,
                "cta": cta,
                "tags": tags,
                "localizations": localizations if localizations else None,
            }
        elif is_localize:
            result = {}
            for city in cities or ["广州"]:
                result[city] = {
                    "title": f"{city}{topic}",
                    "body_text": f"{city}版本：{topic}实测对比，型材壁厚1.8mm，中空钢化玻璃，安装2天搞定。关注我，装修少走弯路！",
                    "tags": [city, "本地化", "门窗选购"],
                }
            if not result:
                result = {
                    "广州": {
                        "title": f"广州{topic}",
                        "body_text": f"广州版本：{topic}实测",
                        "tags": ["广州"],
                    }
                }
        else:
            # Copywriting style
            titles = {
                "douyin": f"{topic}实测！换完窗户家里安静了",
                "xiaohongshu": f"装修小白必看！{topic}避坑3要点",
                "wechat_mp": f"{topic}选购指南：从型材到安装全解析",
            }
            title = titles.get(platform, f"{topic} - 文案版本{index + 1}")

            bodies = {
                "douyin": f"最近很多朋友问{topic}怎么选，今天给大家整理了3个避坑要点。第一，看型材壁厚不低于1.8mm；第二，密封条选三元乙丙；第三，玻璃认准3C认证。关注我，装修少走弯路！",
                "xiaohongshu": f"姐妹们！{topic}真的要重视，我家之前窗户漏风，换了断桥铝之后冬天暖和多了。分享3个选购要点：1.型材壁厚≥1.4mm 2.玻璃选3C认证中空钢化 3.五金认准进口品牌",
                "wechat_mp": f"关于{topic}，很多业主都有疑问。本文从型材选择、玻璃配置、五金品牌、安装工艺四个维度，为您详细解析门窗选购的关键要点。博雅敏格提供免费上门测量服务，具体以门店实测为准。",
            }
            body_text = bodies.get(platform, bodies["douyin"])

            tags_pool = [
                "门窗选购",
                "装修避坑",
                "实测对比",
                "阳台封窗",
                "隔音实测",
                "断桥铝",
                "旧窗改造",
            ]
            tags = rng.sample(tags_pool, min(3, len(tags_pool)))

            result = {
                "title": title,
                "body_text": body_text,
                "tags": tags,
            }

        if knowledge_references:
            result["knowledge_references"] = knowledge_references

        return json.dumps(result, ensure_ascii=False)
