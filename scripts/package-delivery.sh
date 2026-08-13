#!/bin/sh
set -eu
umask 077

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

mkdir -p dist
STAMP=$(date +%Y%m%d-%H%M%S)
OUTPUT="dist/ai-social-media-$STAMP.tar.gz"
CHECKSUM="${OUTPUT}.sha256"
PARTIAL="${OUTPUT}.partial"
FILE_LIST=$(mktemp)

cleanup() {
    rm -f "$FILE_LIST" "$PARTIAL"
}
trap cleanup EXIT INT TERM HUP

find . \
    \( -path './.git' \
       -o -path './.venv' \
       -o -path './dist' \
       -o -path './backups' \
       -o -path './data' \
       -o -path './backend/data' \
       -o -path './frontend/node_modules' \
       -o -path './frontend/dist' \
       -o -name '__pycache__' \
       -o -name '.pytest_cache' \
       -o -name '.ruff_cache' \
       -o -name 'tmp_*' \) -prune -o \
    \( -name '.env*' ! -name '.env.example' \) -prune -o \
    \( -name '.local-ports.env' \
       -o -name '.DS_Store' \
       -o -name '*.pyc' \
       -o -path './frontend/src/views/content/__access_test.txt' \) -prune -o \
    \( -type f -o -type l \) -print0 > "$FILE_LIST"

COPYFILE_DISABLE=1 tar --null -czf "$PARTIAL" -T "$FILE_LIST"
mv "$PARTIAL" "$OUTPUT"

python3 - "$OUTPUT" <<'PY'
import sys
import tarfile
from pathlib import PurePosixPath

archive = sys.argv[1]
required = {"README.md", "DEPLOY.md", ".env.example", "docker-compose.yml", "docker-compose.prod.yml"}
present = set()
with tarfile.open(archive, "r:gz") as package:
    for member in package.getmembers():
        path = PurePosixPath(member.name)
        parts = tuple(part for part in path.parts if part != ".")
        normalized = "/".join(parts)
        present.add(normalized)
        if path.is_absolute() or ".." in parts:
            raise SystemExit(f"交付包包含不安全路径：{member.name}")
        if parts and parts[-1].startswith(".env") and parts[-1] != ".env.example":
            raise SystemExit(f"交付包包含环境密钥文件：{member.name}")
        if any(part in {".git", ".venv", "node_modules", "backups", "__pycache__"} for part in parts):
            raise SystemExit(f"交付包包含禁止目录：{member.name}")

missing = sorted(required - present)
if missing:
    raise SystemExit("交付包缺少必要文件：" + ", ".join(missing))
PY

if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$OUTPUT" > "$CHECKSUM"
else
    shasum -a 256 "$OUTPUT" > "$CHECKSUM"
fi

echo "$OUTPUT"
echo "$CHECKSUM"
