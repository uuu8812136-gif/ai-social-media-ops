"""Synapse 内嵌引擎的 Celery worker 任务。

为避免阻塞 FastAPI 主进程，Playwright 操作放在 Celery worker 里执行：
- run_publish_task: 异步执行发布任务
- run_cookie_validate: 异步校验 cookie

这些任务在 worker 进程中通过 asyncio.run() 调度协程，不在主进程的 event loop 里运行。
"""
