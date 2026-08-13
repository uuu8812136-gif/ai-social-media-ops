#!/usr/bin/env bash
# 安装到用户 Library 后由 LaunchAgent 执行。
# 运行时不访问外置项目目录，避免 macOS 可移动卷后台权限限制。

set -euo pipefail
umask 077

RUNTIME_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "${RUNTIME_DIR}/runtime.env" ]; then
  # 该文件只包含安装脚本写入并校验过的简单值。
  # shellcheck disable=SC1091
  . "${RUNTIME_DIR}/runtime.env"
fi

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ai-social-media}"
BACKUP_DIR="${RUNTIME_DIR}/backups"
RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-7}"
SCREENSHOT_DAYS="${SCREENSHOT_RETAIN_DAYS:-7}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
MANIFEST="${BACKUP_DIR}/manifest_${TIMESTAMP}.sha256"
TMP_DIR=""

case "${PROJECT_NAME}" in
  ""|*[!A-Za-z0-9_.-]*) echo "无效的 Compose 项目名" >&2; exit 2 ;;
esac
case "${RETAIN_DAYS}:${SCREENSHOT_DAYS}" in
  *[!0-9:]*|:*) echo "保留天数必须是非负整数" >&2; exit 2 ;;
esac

cleanup() {
  [ -z "${TMP_DIR}" ] || rm -rf "${TMP_DIR}"
  find "${BACKUP_DIR}" -name '*.partial' -type f -delete 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP

DOCKER_BIN="$(command -v docker 2>/dev/null || true)"
if [ -z "${DOCKER_BIN}" ] &&
   [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then
  DOCKER_BIN=/Applications/Docker.app/Contents/Resources/bin/docker
fi
if [ -z "${DOCKER_BIN}" ]; then
  echo "未找到 Docker" >&2
  exit 1
fi
if ! "${DOCKER_BIN}" info >/dev/null 2>&1; then
  echo "Docker daemon 不可用" >&2
  exit 1
fi

container_for() {
  service=$1
  "${DOCKER_BIN}" ps \
    --filter "label=com.docker.compose.project=${PROJECT_NAME}" \
    --filter "label=com.docker.compose.service=${service}" \
    --format '{{.ID}}' | head -n 1
}

env_from_container() {
  container=$1
  key=$2
  "${DOCKER_BIN}" inspect "${container}" \
    --format '{{range .Config.Env}}{{println .}}{{end}}' |
    sed -n "s/^${key}=//p" | tail -n 1
}

volume_for() {
  container=$1
  destination=$2
  "${DOCKER_BIN}" inspect "${container}" \
    --format '{{range .Mounts}}{{if eq .Destination "'"${destination}"'"}}{{.Name}}{{end}}{{end}}'
}

mkdir -p "${BACKUP_DIR}/minio" "${BACKUP_DIR}/runtime" \
  "${BACKUP_DIR}/bridge" "${BACKUP_DIR}/config"
chmod 700 "${RUNTIME_DIR}" "${BACKUP_DIR}" "${BACKUP_DIR}/minio" \
  "${BACKUP_DIR}/runtime" "${BACKUP_DIR}/bridge" "${BACKUP_DIR}/config"

POSTGRES_CONTAINER="$(container_for postgres)"
MINIO_CONTAINER="$(container_for minio)"
BACKEND_CONTAINER="$(container_for backend)"
for required in "${POSTGRES_CONTAINER}" "${MINIO_CONTAINER}" "${BACKEND_CONTAINER}"; do
  [ -n "${required}" ] || {
    echo "项目 ${PROJECT_NAME} 的必要容器未运行" >&2
    exit 1
  }
done

DB_USER="$(env_from_container "${POSTGRES_CONTAINER}" POSTGRES_USER)"
DB_NAME="$(env_from_container "${POSTGRES_CONTAINER}" POSTGRES_DB)"
[ -n "${DB_USER}" ] || DB_USER=postgres
[ -n "${DB_NAME}" ] || DB_NAME=ai_social_media

DB_BACKUP="${BACKUP_DIR}/ai_social_media_${TIMESTAMP}.sql.gz"
"${DOCKER_BIN}" exec -i "${POSTGRES_CONTAINER}" \
  pg_dump --no-owner --no-privileges -U "${DB_USER}" "${DB_NAME}" |
  gzip > "${DB_BACKUP}.partial"
gzip -t "${DB_BACKUP}.partial"
mv "${DB_BACKUP}.partial" "${DB_BACKUP}"

MINIO_VOLUME="$(volume_for "${MINIO_CONTAINER}" /data)"
SYNAPSE_VOLUME="$(volume_for "${BACKEND_CONTAINER}" /app/data/synapse)"
BROWSER_VOLUME="$(volume_for "${BACKEND_CONTAINER}" /app/data/browser_profiles)"
CRAWLER_VOLUME="$(volume_for "${BACKEND_CONTAINER}" /app/data/mediacrawler)"
for required in "${MINIO_VOLUME}" "${SYNAPSE_VOLUME}" \
  "${BROWSER_VOLUME}" "${CRAWLER_VOLUME}"; do
  [ -n "${required}" ] || {
    echo "无法解析必要的 Docker 数据卷" >&2
    exit 1
  }
done

MINIO_NAME="minio_${TIMESTAMP}.tar.gz"
"${DOCKER_BIN}" run --rm \
  -v "${MINIO_VOLUME}:/source:ro" \
  -v "${BACKUP_DIR}/minio:/backup" \
  -e "BACKUP_NAME=${MINIO_NAME}" \
  alpine:3.22 sh -ec \
  'umask 077; tar -C /source -czf "/backup/${BACKUP_NAME}.partial" .; mv "/backup/${BACKUP_NAME}.partial" "/backup/${BACKUP_NAME}"'

RUNTIME_NAME="runtime_${TIMESTAMP}.tar.gz"
"${DOCKER_BIN}" run --rm \
  -v "${SYNAPSE_VOLUME}:/source/synapse:ro" \
  -v "${BROWSER_VOLUME}:/source/browser_profiles:ro" \
  -v "${CRAWLER_VOLUME}:/source/mediacrawler:ro" \
  -v "${BACKUP_DIR}/runtime:/backup" \
  -e "BACKUP_NAME=${RUNTIME_NAME}" \
  alpine:3.22 sh -ec \
  'umask 077; tar -C /source -czf "/backup/${BACKUP_NAME}.partial" synapse browser_profiles mediacrawler; mv "/backup/${BACKUP_NAME}.partial" "/backup/${BACKUP_NAME}"'

BRIDGE_NAME=""
BRIDGE_PROFILE_ROOT="${HOME}/Library/Caches/ai-social-host-browser/profiles"
if [ -d "${BRIDGE_PROFILE_ROOT}" ]; then
  BRIDGE_NAME="bridge_${TIMESTAMP}.tar.gz"
  COPYFILE_DISABLE=1 tar -C "$(dirname "${BRIDGE_PROFILE_ROOT}")" \
    -czf "${BACKUP_DIR}/bridge/${BRIDGE_NAME}.partial" profiles
  mv "${BACKUP_DIR}/bridge/${BRIDGE_NAME}.partial" \
    "${BACKUP_DIR}/bridge/${BRIDGE_NAME}"
fi

TMP_DIR="$(mktemp -d "${RUNTIME_DIR}/.config_${TIMESTAMP}.XXXXXX")"
"${DOCKER_BIN}" inspect "${BACKEND_CONTAINER}" \
  --format '{{range .Config.Env}}{{println .}}{{end}}' > "${TMP_DIR}/.env"
chmod 600 "${TMP_DIR}/.env"
CONFIG_NAME="config_${TIMESTAMP}.tar.gz"
COPYFILE_DISABLE=1 tar -C "${TMP_DIR}" \
  -czf "${BACKUP_DIR}/config/${CONFIG_NAME}.partial" .env
mv "${BACKUP_DIR}/config/${CONFIG_NAME}.partial" \
  "${BACKUP_DIR}/config/${CONFIG_NAME}"

CHECKSUM_FILES=(
  "$(basename "${DB_BACKUP}")"
  "minio/${MINIO_NAME}"
  "runtime/${RUNTIME_NAME}"
  "config/${CONFIG_NAME}"
)
[ -z "${BRIDGE_NAME}" ] || CHECKSUM_FILES+=("bridge/${BRIDGE_NAME}")
(
  cd "${BACKUP_DIR}"
  shasum -a 256 "${CHECKSUM_FILES[@]}" > "$(basename "${MANIFEST}")"
)
chmod 600 "${MANIFEST}"

"${DOCKER_BIN}" exec -i "${BACKEND_CONTAINER}" sh -ec "
  if [ -d /app/data/synapse/screenshots ]; then
    find /app/data/synapse/screenshots -type f -mtime +${SCREENSHOT_DAYS} -delete
    find /app/data/synapse/screenshots -depth -type d -empty -delete
  fi
"

find "${BACKUP_DIR}" -name 'ai_social_media_*.sql.gz' -type f \
  -mtime "+${RETAIN_DAYS}" -delete
find "${BACKUP_DIR}/minio" -name 'minio_*.tar.gz' -type f \
  -mtime "+${RETAIN_DAYS}" -delete
find "${BACKUP_DIR}/runtime" -name 'runtime_*.tar.gz' -type f \
  -mtime "+${RETAIN_DAYS}" -delete
find "${BACKUP_DIR}/bridge" -name 'bridge_*.tar.gz' -type f \
  -mtime "+${RETAIN_DAYS}" -delete
find "${BACKUP_DIR}/config" -name 'config_*.tar.gz' -type f \
  -mtime "+${RETAIN_DAYS}" -delete
find "${BACKUP_DIR}" -name 'manifest_*.sha256' -type f \
  -mtime "+${RETAIN_DAYS}" -delete

echo "维护完成：${MANIFEST}"
