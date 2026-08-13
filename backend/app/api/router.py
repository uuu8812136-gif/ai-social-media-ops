from fastapi import APIRouter

from app.api.v1 import (
    assets,
    auth,
    calendar,
    content,
    crawler,
    dashboard,
    dealers,
    knowledge,
    leads,
    llm_settings,
    risk,
    social_accounts,
    social_publish,
    users,
    wecom,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(content.router)
api_router.include_router(calendar.router)
api_router.include_router(assets.router)
api_router.include_router(leads.router)
api_router.include_router(dealers.router)
api_router.include_router(knowledge.router)
api_router.include_router(llm_settings.router)
api_router.include_router(users.router)
api_router.include_router(risk.router)
api_router.include_router(wecom.router)
api_router.include_router(dashboard.router)
# 社媒矩阵：扫码登录、Cookie 管理、发布任务、采集
api_router.include_router(social_accounts.router)
api_router.include_router(social_publish.router)
api_router.include_router(crawler.router)
