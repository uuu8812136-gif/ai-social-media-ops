"""原地轮换数据库敏感字段和社媒 Cookie 的加密密钥。

运行前必须先完成数据库和数据卷备份。密钥只从进程环境读取：
OLD_PHONE_ENCRYPTION_KEY / NEW_PHONE_ENCRYPTION_KEY
OLD_COOKIE_ENCRYPTION_KEY / NEW_COOKIE_ENCRYPTION_KEY
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path

from cryptography.fernet import InvalidToken
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.utils.encryption import _fernet_from_secret


def _required(name: str, min_length: int = 1) -> str:
    value = os.environ.get(name, "")
    if len(value) < min_length:
        raise RuntimeError(f"{name} 缺失或长度不足 {min_length}")
    return value


def _decrypt_phone_value(value: str, old_fernet) -> str:
    try:
        return old_fernet.decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("数据库中存在无法用旧密钥解密的敏感字段") from exc


async def rotate() -> None:
    old_phone = _fernet_from_secret(_required("OLD_PHONE_ENCRYPTION_KEY"))
    new_phone = _fernet_from_secret(_required("NEW_PHONE_ENCRYPTION_KEY", 32))
    old_cookie = _fernet_from_secret(_required("OLD_COOKIE_ENCRYPTION_KEY"))
    new_cookie = _fernet_from_secret(_required("NEW_COOKIE_ENCRYPTION_KEY", 32))
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql+asyncpg://"):
        raise RuntimeError("DATABASE_URL 必须使用 postgresql+asyncpg")

    cookie_dir = Path(
        os.environ.get("SYNAPSE_COOKIE_DIR", "data/synapse/cookies")
    ).resolve()
    cookie_files = sorted(cookie_dir.glob("*.json")) if cookie_dir.exists() else []

    # 先在内存中验证所有旧密文，任何一个不可解密都不落盘。
    cookie_payloads: dict[Path, bytes] = {}
    for path in cookie_files:
        raw = path.read_text(encoding="utf-8")
        if raw.lstrip().startswith(("{", "[")):
            plaintext = raw
        else:
            try:
                plaintext = old_cookie.decrypt(raw.encode()).decode()
            except InvalidToken as exc:
                raise RuntimeError(f"Cookie 文件无法用旧密钥解密：{path.name}") from exc
        json.loads(plaintext)
        cookie_payloads[path] = new_cookie.encrypt(plaintext.encode())

    engine = create_async_engine(database_url)
    backups: dict[Path, Path] = {}
    staged: dict[Path, Path] = {}
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        lead_rows = (
            await connection.execute(text("SELECT id, customer_phone FROM leads"))
        ).mappings().all()
        llm_rows = (
            await connection.execute(
                text(
                    "SELECT id, api_key_encrypted "
                    "FROM llm_provider_configs WHERE api_key_encrypted IS NOT NULL"
                )
            )
        ).mappings().all()

        lead_updates = [
            (
                row["id"],
                new_phone.encrypt(
                    _decrypt_phone_value(row["customer_phone"], old_phone).encode()
                ).decode(),
            )
            for row in lead_rows
        ]
        llm_updates = [
            (
                row["id"],
                new_phone.encrypt(
                    _decrypt_phone_value(row["api_key_encrypted"], old_phone).encode()
                ).decode(),
            )
            for row in llm_rows
        ]

        for path, payload in cookie_payloads.items():
            tmp_path = path.with_name(f".{path.name}.rotation-new")
            backup_path = path.with_name(f".{path.name}.rotation-old")
            tmp_path.write_bytes(payload)
            tmp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            staged[path] = tmp_path
            os.replace(path, backup_path)
            backups[path] = backup_path
            os.replace(tmp_path, path)

        for row_id, encrypted in lead_updates:
            await connection.execute(
                text("UPDATE leads SET customer_phone=:value WHERE id=:id"),
                {"id": row_id, "value": encrypted},
            )
        for row_id, encrypted in llm_updates:
            await connection.execute(
                text(
                    "UPDATE llm_provider_configs "
                    "SET api_key_encrypted=:value WHERE id=:id"
                ),
                {"id": row_id, "value": encrypted},
            )
        await transaction.commit()
    except Exception:
        if transaction.is_active:
            await transaction.rollback()
        for path, backup_path in backups.items():
            if backup_path.exists():
                os.replace(backup_path, path)
        raise
    finally:
        await connection.close()
        await engine.dispose()
        for tmp_path in staged.values():
            tmp_path.unlink(missing_ok=True)

    for backup_path in backups.values():
        backup_path.unlink(missing_ok=True)
    print(
        "加密密钥轮换完成："
        f"线索 {len(lead_updates)} 条，模型配置 {len(llm_updates)} 条，"
        f"Cookie {len(cookie_payloads)} 个"
    )


if __name__ == "__main__":
    asyncio.run(rotate())
