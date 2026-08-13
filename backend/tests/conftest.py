"""共享 pytest fixtures 与数据库可达性守卫。

每个测试后释放异步 DB 引擎连接池，避免 asyncpg 连接跨事件循环复用导致
InterfaceError（pytest-asyncio 默认每个测试用独立事件循环，而连接池里的
连接绑定到创建它的循环）。

同时探测数据库是否可达：不可达（如本地无 Postgres / Docker hostname 无法解析）
时，对共享数据库 client fixture 的集成用例整文件 skip，而非在 fixture 阶段报连接错误。
不依赖该 fixture 的能力表和纯逻辑用例不受影响。
"""

import socket
from urllib.parse import urlparse

import pytest

from app.core.config import get_settings
from app.core.database import engine


def _database_reachable() -> bool:
    """用短超时 TCP 探测数据库端口是否可连，避免慢速失败。"""
    url = get_settings().DATABASE_URL
    parsed = urlparse(url.replace("+asyncpg", "").replace("+psycopg2", ""))
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


_DB_OK = _database_reachable()

# 依赖数据库的测试文件（连不上 DB 时整文件 skip）
_DB_DEPENDENT_FILES = ("test_api.py",)


def pytest_collection_modifyitems(config, items):
    if _DB_OK:
        return
    skip_db = pytest.mark.skip(reason="数据库不可达，跳过依赖 DB 的集成用例")
    for item in items:
        in_db_file = any(f in str(item.fspath) for f in _DB_DEPENDENT_FILES)
        if in_db_file:
            item.add_marker(skip_db)


@pytest.fixture(autouse=True)
async def _dispose_db_engine():
    yield
    await engine.dispose()
