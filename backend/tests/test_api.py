import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine, get_db
from app.core.security import get_password_hash
from app.main import app
from app.api.v1 import llm_settings
from app.models.user import User
from app.services.llm_client import LLMClient


@pytest.fixture
async def client():
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

        async def override_get_db():
            yield session

        app.dependency_overrides[get_db] = override_get_db
        try:
            # 测试不依赖生产管理员当前口令；修改处于外层事务内，fixture
            # 结束后整体回滚，不会污染真实账号。
            admin = await session.scalar(
                select(User).where(User.username == "admin")
            )
            if admin is not None:
                admin.password_hash = get_password_hash("admin123")
                await session.flush()
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://health.internal"
            ) as ac:
                yield ac
        finally:
            app.dependency_overrides.pop(get_db, None)
            await session.close()
            await transaction.rollback()


async def _login(client, username="admin", password="admin123"):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200
    return resp.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_login(client):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 0
    assert "access_token" in data["data"]


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_replay_protection(client):
    login = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    refresh_token = login.json()["data"]["refresh_token"]
    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["refresh_token"] != refresh_token

    replayed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert replayed.status_code == 401


@pytest.mark.asyncio
async def test_risk_check_absolute_word(client):
    token = await _login(client)
    resp = await client.post(
        "/api/v1/risk/check",
        json={"content": "我们是最好的门窗品牌，行业第一"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["passed"] is False
    assert any(i["severity"] == "high" for i in data["issues"])


@pytest.mark.asyncio
async def test_wecom_keyword(client, monkeypatch):
    from app.api.v1 import wecom

    monkeypatch.setattr(wecom.settings, "APP_ENV", "test")
    resp = await client.post(
        "/api/v1/wecom/callback",
        json={"sender_id": "unknown", "content": "随便聊聊"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["handled"] is False


@pytest.mark.asyncio
async def test_dashboard_overview(client):
    token = await _login(client)
    resp = await client.get(
        "/api/v1/dashboard/overview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "accounts" in data
    assert "contents" in data
    assert "leads" in data


@pytest.mark.asyncio
async def test_dashboard_content_stats(client):
    token = await _login(client)
    resp = await client.get(
        "/api/v1/dashboard/content/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "total" in data
    assert "publish_rate" in data


@pytest.mark.asyncio
async def test_dashboard_operations_reports_actionable_states(client):
    token = await _login(client)
    resp = await client.get(
        "/api/v1/dashboard/operations?days=7",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) >= {"publish", "accounts", "crawler", "alerts", "platforms"}
    assert "unknown" in data["publish"]
    assert "success_rate" in data["publish"]
    assert all("acceptance" in platform for platform in data["platforms"])


@pytest.mark.asyncio
async def test_llm_settings_encrypt_and_mask_api_key(client, monkeypatch):
    async def allow_test_endpoint(_base_url):
        return None

    async def fake_generate(self, **_kwargs):
        return ["OK"]

    monkeypatch.setattr(llm_settings, "ensure_safe_llm_base_url", allow_test_endpoint)
    monkeypatch.setattr(LLMClient, "generate", fake_generate)

    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "provider_name": "自定义测试模型",
        "protocol": "responses",
        "base_url": "https://llm.example/v1",
        "model": "test-model",
        "api_key": "secret-api-key-1234",
        "timeout_seconds": 90,
    }
    saved = await client.put("/api/v1/settings/llm", json=payload, headers=headers)
    assert saved.status_code == 200
    saved_data = saved.json()["data"]
    assert saved_data["api_key_configured"] is True
    assert saved_data["api_key_hint"] == "****1234"
    assert "secret-api-key" not in saved.text

    fetched = await client.get("/api/v1/settings/llm", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["source"] == "database"
    assert "secret-api-key" not in fetched.text

    test_payload = {**payload, "api_key": None}
    tested = await client.post(
        "/api/v1/settings/llm/test", json=test_payload, headers=headers
    )
    assert tested.status_code == 200
    assert tested.json()["data"]["ok"] is True

    restored = await client.delete("/api/v1/settings/llm", headers=headers)
    assert restored.status_code == 200
    assert restored.json()["data"]["source"] == "environment"


@pytest.mark.asyncio
async def test_system_user_management_flow(client):
    admin_token = await _login(client)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    created = await client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": "pytest_operator",
            "full_name": "测试运营员",
            "role": "operator",
            "password": "TestPass123",
        },
    )
    assert created.status_code == 200
    user = created.json()["data"]
    assert user["username"] == "pytest_operator"
    assert user["is_active"] is True
    assert "password" not in created.text.lower()
    user_id = user["id"]

    duplicate = await client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": "pytest_operator",
            "full_name": "重复账号",
            "role": "operator",
            "password": "TestPass123",
        },
    )
    assert duplicate.status_code == 409

    operator_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "PYTEST_OPERATOR", "password": "TestPass123"},
    )
    assert operator_login.status_code == 200
    operator_data = operator_login.json()["data"]
    operator_refresh = operator_data["refresh_token"]
    operator_headers = {"Authorization": f"Bearer {operator_data['access_token']}"}
    forbidden = await client.get("/api/v1/users", headers=operator_headers)
    assert forbidden.status_code == 403

    reset = await client.post(
        f"/api/v1/users/{user_id}/reset-password",
        headers=admin_headers,
        json={"new_password": "NewPass456"},
    )
    assert reset.status_code == 200
    revoked_after_reset = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": operator_refresh}
    )
    assert revoked_after_reset.status_code == 401
    old_access_after_reset = await client.get(
        "/api/v1/auth/me", headers=operator_headers
    )
    assert old_access_after_reset.status_code == 401
    old_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "pytest_operator", "password": "TestPass123"},
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "pytest_operator", "password": "NewPass456"},
    )
    assert new_login.status_code == 200

    disabled = await client.put(
        f"/api/v1/users/{user_id}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["data"]["is_active"] is False
    disabled_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "pytest_operator", "password": "NewPass456"},
    )
    assert disabled_login.status_code == 403
    disabled_refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_login.json()["data"]["refresh_token"]},
    )
    assert disabled_refresh.status_code == 401

    me = await client.get("/api/v1/auth/me", headers=admin_headers)
    self_disable = await client.put(
        f"/api/v1/users/{me.json()['data']['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert self_disable.status_code == 400


@pytest.mark.asyncio
async def test_social_accounts_list(client):
    token = await _login(client)
    resp = await client.get(
        "/api/v1/social/accounts/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


@pytest.mark.asyncio
async def test_legacy_mock_routes_removed(client):
    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    accounts = await client.get("/api/v1/accounts/", headers=headers)
    publish_dashboard = await client.get("/api/v1/publish/dashboard", headers=headers)
    assert accounts.status_code == 404
    assert publish_dashboard.status_code == 404


@pytest.mark.asyncio
async def test_leads_create(client):
    token = await _login(client)
    resp = await client.post(
        "/api/v1/leads/",
        json={
            "pool_type": "consumer",
            "customer_name": "测试客户",
            "customer_phone": "13900139000",
            "requirement": "断桥铝封阳台",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["customer_name"] == "测试客户"
    assert "****" in data["customer_phone_masked"]


@pytest.mark.asyncio
async def test_leads_stats(client):
    token = await _login(client)
    resp = await client.get(
        "/api/v1/leads/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert "conversion_rate" in resp.json()["data"]
