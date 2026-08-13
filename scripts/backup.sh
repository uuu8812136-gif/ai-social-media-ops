#!/usr/bin/env bash
# AI 社媒矩阵运营系统 数据库 + MinIO 备份脚本
# 用法：bash scripts/backup.sh
# 建议配合 crontab 每天 03:00 执行：0 3 * * * cd /opt/ai-social-media && bash scripts/backup.sh >> /var/log/backup.log 2>&1

set -euo pipefail
umask 077

# ── 配置 ──
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "${PROJECT_DIR}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "${PROJECT_DIR}/.env"
  set +a
fi
BACKUP_DIR="${PROJECT_DIR}/backups"
RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-7}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-ai_social_media}"
COMPOSE_SERVICE="postgres"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DB_BACKUP="${BACKUP_DIR}/ai_social_media_${TIMESTAMP}.sql.gz"
MINIO_BACKUP="${BACKUP_DIR}/minio/minio_${TIMESTAMP}.tar.gz"
RUNTIME_BACKUP="${BACKUP_DIR}/runtime/runtime_${TIMESTAMP}.tar.gz"
BRIDGE_BACKUP="${BACKUP_DIR}/bridge/bridge_${TIMESTAMP}.tar.gz"
CONFIG_BACKUP="${BACKUP_DIR}/config/config_${TIMESTAMP}.tar.gz"
MANIFEST="${BACKUP_DIR}/manifest_${TIMESTAMP}.sha256"
DB_PARTIAL="${DB_BACKUP}.partial"
MINIO_PARTIAL="${MINIO_BACKUP}.partial"
RUNTIME_PARTIAL="${RUNTIME_BACKUP}.partial"
BRIDGE_PARTIAL="${BRIDGE_BACKUP}.partial"
CONFIG_PARTIAL="${CONFIG_BACKUP}.partial"
MINIO_TMP=""

cleanup() {
  rm -f "${DB_PARTIAL}" "${MINIO_PARTIAL}" "${RUNTIME_PARTIAL}" \
    "${BRIDGE_PARTIAL}" "${CONFIG_PARTIAL}"
  if [ -n "${MINIO_TMP}" ]; then
    rm -rf "${MINIO_TMP}"
  fi
}
trap cleanup EXIT INT TERM HUP

mkdir -p "${BACKUP_DIR}/minio" "${BACKUP_DIR}/runtime" \
  "${BACKUP_DIR}/bridge" "${BACKUP_DIR}/config"

DOCKER_BIN="$(command -v docker 2>/dev/null || true)"
if [ -z "${DOCKER_BIN}" ] && [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then
  DOCKER_BIN=/Applications/Docker.app/Contents/Resources/bin/docker
  export PATH="/Applications/Docker.app/Contents/Resources/bin:${PATH}"
fi
if [ -z "${DOCKER_BIN}" ]; then
  echo "未找到 Docker" >&2
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== 开始备份 ====="

# ── 1. PostgreSQL 数据库备份 ──
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 备份数据库 ${DB_NAME}..."
cd "${PROJECT_DIR}"
"${DOCKER_BIN}" compose exec -T "${COMPOSE_SERVICE}" \
  pg_dump --no-owner --no-privileges -U "${DB_USER}" "${DB_NAME}" |
  gzip > "${DB_PARTIAL}"

if [ ! -s "${DB_PARTIAL}" ] || ! gzip -t "${DB_PARTIAL}"; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 数据库备份失败：文件为空" >&2
  exit 1
fi
mv "${DB_PARTIAL}" "${DB_BACKUP}"

DB_SIZE=$(du -h "${DB_BACKUP}" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 数据库备份完成：${DB_BACKUP} (${DB_SIZE})"

# ── 2. MinIO 素材目录备份（tar 打包数据卷）──
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 备份 MinIO 素材..."
MINIO_CONTAINER=$("${DOCKER_BIN}" compose ps --quiet minio)
if [ -z "${MINIO_CONTAINER}" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 未找到运行中的 MinIO 容器" >&2
  exit 1
fi
MINIO_TMP=$(mktemp -d "${BACKUP_DIR}/.minio_${TIMESTAMP}.XXXXXX")
"${DOCKER_BIN}" cp "${MINIO_CONTAINER}:/data/." "${MINIO_TMP}"
COPYFILE_DISABLE=1 tar -C "${MINIO_TMP}" -czf "${MINIO_PARTIAL}" .

if [ ! -s "${MINIO_PARTIAL}" ] || ! tar -tzf "${MINIO_PARTIAL}" >/dev/null; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️  MinIO 备份为空（可能无素材或卷不存在）"
  rm -f "${MINIO_PARTIAL}"
else
  mv "${MINIO_PARTIAL}" "${MINIO_BACKUP}"
  MINIO_SIZE=$(du -h "${MINIO_BACKUP}" | cut -f1)
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ MinIO 备份完成：${MINIO_BACKUP} (${MINIO_SIZE})"
fi

# ── 3. 发布引擎运行数据（Cookie、截图、浏览器配置、采集文件）──
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 备份发布引擎运行数据..."
"${DOCKER_BIN}" compose exec -T backend \
  tar -C /app/data -czf - synapse browser_profiles mediacrawler \
  > "${RUNTIME_PARTIAL}"
if [ ! -s "${RUNTIME_PARTIAL}" ] || ! tar -tzf "${RUNTIME_PARTIAL}" >/dev/null; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 发布引擎运行数据备份失败" >&2
  exit 1
fi
mv "${RUNTIME_PARTIAL}" "${RUNTIME_BACKUP}"

# ── 4. 宿主真实浏览器会话与关键配置 ──
if [ -d "${PROJECT_DIR}/host-browser-bridge/.runtime/profiles" ]; then
  COPYFILE_DISABLE=1 tar -C "${PROJECT_DIR}/host-browser-bridge/.runtime" \
    -czf "${BRIDGE_PARTIAL}" profiles
  tar -tzf "${BRIDGE_PARTIAL}" >/dev/null
  mv "${BRIDGE_PARTIAL}" "${BRIDGE_BACKUP}"
fi

CONFIG_FILES=()
[ ! -f "${PROJECT_DIR}/.env" ] || CONFIG_FILES+=(".env")
[ ! -f "${PROJECT_DIR}/.local-ports.env" ] || CONFIG_FILES+=(".local-ports.env")
if [ "${#CONFIG_FILES[@]}" -gt 0 ]; then
  COPYFILE_DISABLE=1 tar -C "${PROJECT_DIR}" -czf "${CONFIG_PARTIAL}" \
    "${CONFIG_FILES[@]}"
  tar -tzf "${CONFIG_PARTIAL}" >/dev/null
  mv "${CONFIG_PARTIAL}" "${CONFIG_BACKUP}"
fi

# ── 5. 校验清单：恢复前必须整单校验通过 ──
CHECKSUM_FILES=(
  "$(basename "${DB_BACKUP}")"
  "minio/$(basename "${MINIO_BACKUP}")"
  "runtime/$(basename "${RUNTIME_BACKUP}")"
)
[ ! -f "${BRIDGE_BACKUP}" ] || CHECKSUM_FILES+=("bridge/$(basename "${BRIDGE_BACKUP}")")
[ ! -f "${CONFIG_BACKUP}" ] || CHECKSUM_FILES+=("config/$(basename "${CONFIG_BACKUP}")")
(
  cd "${BACKUP_DIR}"
  shasum -a 256 "${CHECKSUM_FILES[@]}" > "$(basename "${MANIFEST}")"
)
chmod 600 "${MANIFEST}"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 校验清单：${MANIFEST}"

# ── 6. 清理过期备份 ──
find "${BACKUP_DIR}" -name "ai_social_media_*.sql.gz" -type f -mtime "+${RETAIN_DAYS}" -delete
find "${BACKUP_DIR}/minio" -name "minio_*.tar.gz" -type f -mtime "+${RETAIN_DAYS}" -delete
find "${BACKUP_DIR}/runtime" -name "runtime_*.tar.gz" -type f -mtime "+${RETAIN_DAYS}" -delete
find "${BACKUP_DIR}/bridge" -name "bridge_*.tar.gz" -type f -mtime "+${RETAIN_DAYS}" -delete
find "${BACKUP_DIR}/config" -name "config_*.tar.gz" -type f -mtime "+${RETAIN_DAYS}" -delete
find "${BACKUP_DIR}" -name "manifest_*.sha256" -type f -mtime "+${RETAIN_DAYS}" -delete
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 已清理 ${RETAIN_DAYS} 天前的旧备份"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== 备份完成 ====="
