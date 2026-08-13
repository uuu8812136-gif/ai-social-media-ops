"""Read-only production-path smoke test for a running AI social-media stack."""

import argparse
import sys

try:
    import requests
except ImportError:
    print("请安装 requests: pip install requests")
    sys.exit(1)


class SmokeTest:
    def __init__(self, api_base: str, username: str, password: str):
        self.api_base = api_base.rstrip("/")
        self.username = username
        self.password = password
        self.access_token = ""
        self.refresh_token = ""
        self.passed = 0
        self.failed = 0

    def log(self, name: str, ok: bool, detail: str = "") -> bool:
        print(
            f"  {'PASS' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else "")
        )
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        return ok

    def request(self, method: str, path: str, *, use_auth: bool = True, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        if use_auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        try:
            return requests.request(
                method,
                f"{self.api_base}{path}",
                headers=headers,
                timeout=15,
                **kwargs,
            )
        except requests.RequestException as exc:
            self.log(f"{method} {path}", False, str(exc))
            return None

    @staticmethod
    def success_response(response) -> bool:
        if response is None or response.status_code != 200:
            return False
        try:
            return response.json().get("code") == 0
        except (ValueError, AttributeError):
            return False

    def run(self) -> bool:
        print(f"\nAI 社媒平台冒烟测试 - {self.api_base}\n")

        live = self.request("GET", "/health/live", use_auth=False)
        self.log("存活检查", live is not None and live.status_code == 200)
        ready = self.request("GET", "/health/ready", use_auth=False)
        self.log("就绪检查", ready is not None and ready.status_code == 200)

        unauthorized = self.request("GET", "/api/v1/auth/me", use_auth=False)
        self.log(
            "未授权拦截", unauthorized is not None and unauthorized.status_code == 401
        )

        login = self.request(
            "POST",
            "/api/v1/auth/login",
            use_auth=False,
            json={"username": self.username, "password": self.password},
        )
        login_ok = self.success_response(login)
        if login_ok:
            payload = login.json()["data"]
            self.access_token = payload.get("access_token", "")
            self.refresh_token = payload.get("refresh_token", "")
        if not self.log(
            "管理员登录", login_ok and bool(self.access_token and self.refresh_token)
        ):
            return self.summary()

        checks = (
            ("当前用户", "/api/v1/auth/me"),
            ("仪表盘", "/api/v1/dashboard/overview"),
            ("知识库列表", "/api/v1/knowledge/?page=1&page_size=5"),
            ("社媒平台能力", "/api/v1/social/accounts/platforms"),
            ("采集平台能力", "/api/v1/crawler/platforms"),
            ("素材库列表", "/api/v1/assets/?page=1&page_size=5"),
        )
        for name, path in checks:
            self.log(name, self.success_response(self.request("GET", path)))

        previous_refresh = self.refresh_token
        refreshed = self.request(
            "POST",
            "/api/v1/auth/refresh",
            use_auth=False,
            json={"refresh_token": previous_refresh},
        )
        refresh_ok = self.success_response(refreshed)
        if refresh_ok:
            payload = refreshed.json()["data"]
            self.access_token = payload.get("access_token", "")
            self.refresh_token = payload.get("refresh_token", "")
        self.log(
            "Refresh Token 轮换",
            refresh_ok
            and self.refresh_token
            and self.refresh_token != previous_refresh,
        )

        replay = self.request(
            "POST",
            "/api/v1/auth/refresh",
            use_auth=False,
            json={"refresh_token": previous_refresh},
        )
        self.log(
            "Refresh Token 重放防护", replay is not None and replay.status_code == 401
        )

        logout = self.request(
            "POST",
            "/api/v1/auth/logout",
            use_auth=False,
            json={"refresh_token": self.refresh_token},
        )
        self.log("退出会话撤销", self.success_response(logout))
        invalidated_access = self.request("GET", "/api/v1/auth/me")
        self.log(
            "退出后 Access Token 失效",
            invalidated_access is not None and invalidated_access.status_code == 401,
        )
        return self.summary()

    def summary(self) -> bool:
        total = self.passed + self.failed
        print(f"\n测试结果：{self.passed}/{total} 通过")
        return self.failed == 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://127.0.0.1:8080")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    args = parser.parse_args()
    success = SmokeTest(args.api_base, args.username, args.password).run()
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
