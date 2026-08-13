"""平台级发布/采集人工验收脚本（delivery-level acceptance）。

目的：不依赖单元测试环境，直接对运行中的后端做端到端验收，验证
「自动发布」与「数据采集」两条真实链路是否交付级可用。

默认只读：打印发布/采集平台能力矩阵 + 社媒账号 cookie 状态审计，不产生副作用。
加 --publish / --crawl 才会真实触发链路（需 worker 在跑、账号 cookie 有效）。

用法：
  # 只读审计（能力矩阵 + 账号状态）
  python scripts/publish_acceptance.py --api-base http://localhost:8000

  # 真实发布验收（需有效内容与账号）
  python scripts/publish_acceptance.py --publish \
      --content-id <uuid> --account-id <uuid> --platform xiaohongshu

  # 真实采集验收
  python scripts/publish_acceptance.py --crawl --platform xhs --keyword 断桥铝门窗
"""
from __future__ import annotations

import argparse
import sys
import time

try:
    import requests
except ImportError:
    print("请先安装 requests: pip install requests")
    sys.exit(1)


class Acceptance:
    def __init__(self, api_base: str, username: str, password: str):
        self.api_base = api_base.rstrip("/")
        self.username = username
        self.password = password
        self.token: str | None = None
        self.passed = 0
        self.failed = 0

    # ---- 基础 ----
    def _url(self, path: str) -> str:
        return f"{self.api_base}{path}"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def req(self, method: str, path: str, **kwargs):
        try:
            return requests.request(method, self._url(path), timeout=30, headers=self._headers(), **kwargs)
        except requests.exceptions.RequestException as e:
            print(f"  ⚠️  请求异常 {method} {path}: {e}")
            return None

    def check(self, name: str, ok: bool, detail: str = ""):
        mark = "✅" if ok else "❌"
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
        return ok

    # ---- 步骤 ----
    def login(self) -> bool:
        resp = self.req("POST", "/api/v1/auth/login", json={"username": self.username, "password": self.password})
        ok = resp is not None and resp.status_code == 200
        if ok:
            self.token = resp.json().get("data", {}).get("access_token")
        return self.check("登录", ok and bool(self.token))

    def audit_capabilities(self):
        print("\n== 发布平台能力矩阵 ==")
        resp = self.req("GET", "/api/v1/social/accounts/platforms")
        if resp and resp.status_code == 200:
            for p in resp.json().get("data", []):
                pub = p.get("publish", {})
                print(f"  · {p.get('name'):<6} 发布={pub.get('status_label','?'):<10} "
                      f"扫码登录={'是' if p.get('login',{}).get('qrcode') else '否'} "
                      f"可用={'✔' if pub.get('available') else '✗'}")
            self.check("发布能力接口", True)
        else:
            self.check("发布能力接口", False)

        print("\n== 采集平台能力矩阵 ==")
        resp = self.req("GET", "/api/v1/crawler/platforms")
        if resp and resp.status_code == 200:
            data = resp.json().get("data", {})
            for p in data.get("platforms", []):
                print(f"  · {p.get('name'):<6} 采集={p.get('status_label','?'):<10} "
                      f"可用={'✔' if p.get('crawler_available') else '✗'}")
            self.check("采集能力接口", True, f"引擎可用={data.get('available')}")
        else:
            self.check("采集能力接口", False)

    def audit_accounts(self):
        print("\n== 社媒账号 cookie 状态 ==")
        resp = self.req("GET", "/api/v1/social/accounts/", params={"page_size": 100})
        if not (resp and resp.status_code == 200):
            self.check("账号列表接口", False)
            return
        accounts = resp.json().get("data", []) or []
        if not accounts:
            print("  （无已扫码登录账号，发布验收需先在账号管理扫码）")
        for a in accounts:
            print(f"  · [{a.get('platform')}] {a.get('nickname') or a.get('platform_uid') or a.get('id')} "
                  f"cookie={a.get('cookie_status')}")
        self.check("账号列表接口", True, f"共 {len(accounts)} 个")

    def run_publish(self, content_id: str, account_id: str, platform: str, timeout: int):
        print("\n== 真实发布验收 ==")
        body = {
            "content_id": content_id,
            "targets": [{"social_account_id": account_id, "platform": platform}],
            "publish_mode": "direct",
        }
        resp = self.req("POST", "/api/v1/social/publish/", json=body)
        if not (resp and resp.status_code == 200):
            self.check("创建发布批次", False, resp.text[:200] if resp else "无响应")
            return
        data = resp.json().get("data", {})
        tasks = data.get("tasks", [])
        if not tasks:
            self.check("创建发布批次", False, "无任务")
            return
        task_id = tasks[0]["task_id"]
        self.check("创建发布批次", True, f"task_id={task_id}")
        self._poll_publish(task_id, timeout)

    def _poll_publish(self, task_id: str, timeout: int):
        print(f"  轮询发布任务（最多 {timeout}s）...")
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            resp = self.req("GET", f"/api/v1/social/publish/tasks/{task_id}")
            if resp and resp.status_code == 200:
                t = resp.json().get("data", {})
                st = t.get("status")
                if st != last:
                    print(f"    状态: {st}")
                    last = st
                if st in ("published", "reviewing", "failed", "cancelled", "worker_error", "filled"):
                    ok = st in ("published", "reviewing")
                    self.check("发布任务完成", ok, f"status={st}")
                    print(f"    external_post_id={t.get('external_post_id')}")
                    print(f"    publish_url={t.get('publish_url')}")
                    print(f"    error={t.get('error_message')}")
                    return
            time.sleep(3)
        self.check("发布任务完成", False, "轮询超时（worker 是否在运行？）")

    def run_crawl(self, platform: str, keyword: str, timeout: int):
        print("\n== 真实采集验收 ==")
        body = {
            "name": f"验收-{keyword}",
            "platform": platform,
            "crawler_type": "search",
            "params": {"keywords": keyword, "max_notes": 5},
        }
        resp = self.req("POST", "/api/v1/crawler/jobs", json=body)
        if not (resp and resp.status_code == 200):
            self.check("创建采集任务", False, resp.text[:200] if resp else "无响应")
            return
        job = resp.json().get("data", {})
        job_id = job.get("id")
        self.check("创建采集任务", True, f"job_id={job_id}")
        print(f"  轮询采集任务（最多 {timeout}s）...")
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            resp = self.req("GET", f"/api/v1/crawler/jobs/{job_id}")
            if resp and resp.status_code == 200:
                j = resp.json().get("data", {})
                st = j.get("status")
                if st != last:
                    print(f"    状态: {st}")
                    last = st
                if st in ("succeeded", "failed", "stopped"):
                    self.check("采集任务完成", st == "succeeded",
                               f"status={st} items={j.get('items_count')}")
                    print(f"    output_files={j.get('output_files')}")
                    print(f"    error={j.get('error_message')}")
                    return
            time.sleep(3)
        self.check("采集任务完成", False, "轮询超时（worker 是否在运行？）")

    def summary(self) -> bool:
        total = self.passed + self.failed
        print(f"\n{'='*50}\n验收结果：{self.passed}/{total} 通过")
        return self.failed == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-base", default="http://localhost:8000")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="admin123")
    ap.add_argument("--publish", action="store_true", help="真实触发一次发布")
    ap.add_argument("--crawl", action="store_true", help="真实触发一次采集")
    ap.add_argument("--content-id")
    ap.add_argument("--account-id")
    ap.add_argument("--platform")
    ap.add_argument("--keyword")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    a = Acceptance(args.api_base, args.username, args.password)
    print(f"\n🧪 平台级验收 — {args.api_base}\n")
    if not a.login():
        print("登录失败，终止。")
        sys.exit(1)

    a.audit_capabilities()
    a.audit_accounts()

    if args.publish:
        if not (args.content_id and args.account_id and args.platform):
            print("\n--publish 需同时提供 --content-id --account-id --platform")
        else:
            a.run_publish(args.content_id, args.account_id, args.platform, args.timeout)

    if args.crawl:
        if not (args.platform and args.keyword):
            print("\n--crawl 需同时提供 --platform 与 --keyword")
        else:
            a.run_crawl(args.platform, args.keyword, args.timeout)

    sys.exit(0 if a.summary() else 1)


if __name__ == "__main__":
    main()
