#!/usr/bin/env bash
# 校验或恢复 scripts/backup.sh 生成的完整快照。
# 安全演练：bash scripts/restore.sh --drill backups/manifest_*.sha256
# 正式恢复：bash scripts/restore.sh --execute <manifest> --confirm RESTORE_AI_SOCIAL

set -euo pipefail
umask 077

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${PROJECT_DIR}"

MODE="${1:-}"
MANIFEST="${2:-}"
CONFIRM_FLAG="${3:-}"
CONFIRM_VALUE="${4:-}"
if [ "${MODE}" != "--drill" ] && [ "${MODE}" != "--execute" ]; then
  echo "用法：$0 --drill <manifest.sha256>" >&2
  echo "   或：$0 --execute <manifest.sha256> --confirm RESTORE_AI_SOCIAL" >&2
  exit 2
fi
if [ ! -f "${MANIFEST}" ]; then
  echo "备份清单不存在：${MANIFEST}" >&2
  exit 2
fi
MANIFEST="$(cd "$(dirname "${MANIFEST}")" && pwd)/$(basename "${MANIFEST}")"
BACKUP_DIR="$(dirname "${MANIFEST}")"

verify_manifest() {
  while IFS= read -r line; do
    rel="${line#*  }"
    case "${rel}" in
      ""|/*|*".."*) echo "清单包含不安全路径：${rel}" >&2; exit 1 ;;
    esac
    [ -f "${BACKUP_DIR}/${rel}" ] || {
      echo "清单文件缺失：${rel}" >&2
      exit 1
    }
  done < "${MANIFEST}"
  (cd "${BACKUP_DIR}" && shasum -a 256 -c "$(basename "${MANIFEST}")")
}

manifest_file() {
  pattern=$1
  awk -v pattern="${pattern}" '$2 ~ pattern {print $2; exit}' "${MANIFEST}"
}

verify_archives() {
  db_rel="$(manifest_file 'ai_social_media_.*[.]sql[.]gz$')"
  minio_rel="$(manifest_file '^minio/minio_.*[.]tar[.]gz$')"
  runtime_rel="$(manifest_file '^runtime/runtime_.*[.]tar[.]gz$')"
  [ -n "${db_rel}" ] && gzip -t "${BACKUP_DIR}/${db_rel}"
  [ -n "${minio_rel}" ] && tar -tzf "${BACKUP_DIR}/${minio_rel}" >/dev/null
  [ -n "${runtime_rel}" ] && tar -tzf "${BACKUP_DIR}/${runtime_rel}" >/dev/null
}

verify_manifest
verify_archives

if [ -f "${PROJECT_DIR}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "${PROJECT_DIR}/.env"
  set +a
fi
DB_USER="${POSTGRES_USER:-ai_app}"
DB_NAME="${POSTGRES_DB:-ai_social_media}"
DB_REL="$(manifest_file 'ai_social_media_.*[.]sql[.]gz$')"

if [ "${MODE}" = "--drill" ]; then
  DRILL_DB="ai_restore_drill_$$"
  cleanup_drill() {
    docker compose exec -T postgres dropdb -U postgres --if-exists "${DRILL_DB}" \
      >/dev/null 2>&1 || true
  }
  trap cleanup_drill EXIT INT TERM HUP
  docker compose exec -T postgres createdb -U postgres -O "${DB_USER}" "${DRILL_DB}"
  gzip -dc "${BACKUP_DIR}/${DB_REL}" |
    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "${DB_USER}" \
      -d "${DRILL_DB}" >/dev/null
  TABLE_COUNT="$(
    docker compose exec -T postgres psql -U "${DB_USER}" -d "${DRILL_DB}" -Atc \
      "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
  )"
  VERSION="$(
    docker compose exec -T postgres psql -U "${DB_USER}" -d "${DRILL_DB}" -Atc \
      "SELECT version_num FROM alembic_version LIMIT 1;"
  )"
  echo "恢复演练通过：数据库表 ${TABLE_COUNT} 个，迁移版本 ${VERSION}"
  exit 0
fi

if [ "${CONFIRM_FLAG}" != "--confirm" ] ||
   [ "${CONFIRM_VALUE}" != "RESTORE_AI_SOCIAL" ]; then
  echo "正式恢复会覆盖当前数据库和数据卷，必须追加：--confirm RESTORE_AI_SOCIAL" >&2
  exit 2
fi

CONFIG_REL="$(manifest_file '^config/config_.*[.]tar[.]gz$')"
if [ -n "${CONFIG_REL}" ]; then
  SNAPSHOT_ENV="$(mktemp)"
  trap 'rm -f "${SNAPSHOT_ENV}"' EXIT INT TERM HUP
  tar -xOzf "${BACKUP_DIR}/${CONFIG_REL}" .env > "${SNAPSHOT_ENV}" 2>/dev/null || true
  for key in PHONE_ENCRYPTION_KEY COOKIE_ENCRYPTION_KEY; do
    current="$(sed -n "s/^${key}=//p" .env | tail -n 1)"
    snapshot="$(sed -n "s/^${key}=//p" "${SNAPSHOT_ENV}" | tail -n 1)"
    if [ -n "${snapshot}" ] && [ "${current}" != "${snapshot}" ]; then
      echo "快照 ${key} 与当前配置不同，为避免恢复出不可解密数据已停止。" >&2
      exit 1
    fi
  done
fi

MINIO_REL="$(manifest_file '^minio/minio_.*[.]tar[.]gz$')"
RUNTIME_REL="$(manifest_file '^runtime/runtime_.*[.]tar[.]gz$')"
BRIDGE_REL="$(manifest_file '^bridge/bridge_.*[.]tar[.]gz$')"
RESTORE_TMP="$(mktemp -d)"
trap 'rm -rf "${RESTORE_TMP}"' EXIT INT TERM HUP
mkdir -p "${RESTORE_TMP}/minio" "${RESTORE_TMP}/runtime" "${RESTORE_TMP}/bridge"
tar -xzf "${BACKUP_DIR}/${MINIO_REL}" -C "${RESTORE_TMP}/minio"
tar -xzf "${BACKUP_DIR}/${RUNTIME_REL}" -C "${RESTORE_TMP}/runtime"
[ -z "${BRIDGE_REL}" ] ||
  tar -xzf "${BACKUP_DIR}/${BRIDGE_REL}" -C "${RESTORE_TMP}/bridge"

MINIO_VOLUME="$(docker inspect ai-social-media-minio-1 --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')"
SYNAPSE_VOLUME="$(docker inspect ai-social-media-backend-1 --format '{{range .Mounts}}{{if eq .Destination "/app/data/synapse"}}{{.Name}}{{end}}{{end}}')"
BROWSER_VOLUME="$(docker inspect ai-social-media-backend-1 --format '{{range .Mounts}}{{if eq .Destination "/app/data/browser_profiles"}}{{.Name}}{{end}}{{end}}')"
CRAWLER_VOLUME="$(docker inspect ai-social-media-backend-1 --format '{{range .Mounts}}{{if eq .Destination "/app/data/mediacrawler"}}{{.Name}}{{end}}{{end}}')"
for volume in "${MINIO_VOLUME}" "${SYNAPSE_VOLUME}" "${BROWSER_VOLUME}" "${CRAWLER_VOLUME}"; do
  [ -n "${volume}" ] || { echo "无法解析 Docker 数据卷" >&2; exit 1; }
done

docker compose stop nginx celery backend frontend minio
docker compose exec -T postgres dropdb -U postgres --if-exists "${DB_NAME}"
docker compose exec -T postgres createdb -U postgres -O "${DB_USER}" "${DB_NAME}"
gzip -dc "${BACKUP_DIR}/${DB_REL}" |
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "${DB_USER}" \
    -d "${DB_NAME}" >/dev/null

restore_volume() {
  volume=$1
  source_dir=$2
  docker run --rm \
    -v "${volume}:/target" \
    -v "${source_dir}:/source:ro" \
    alpine:3.22 \
    sh -ec 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; cp -a /source/. /target/'
}
restore_volume "${MINIO_VOLUME}" "${RESTORE_TMP}/minio"
restore_volume "${SYNAPSE_VOLUME}" "${RESTORE_TMP}/runtime/synapse"
restore_volume "${BROWSER_VOLUME}" "${RESTORE_TMP}/runtime/browser_profiles"
restore_volume "${CRAWLER_VOLUME}" "${RESTORE_TMP}/runtime/mediacrawler"

if [ -d "${RESTORE_TMP}/bridge/profiles" ]; then
  host-browser-bridge/stop.sh
  mkdir -p host-browser-bridge/.runtime/profiles
  find host-browser-bridge/.runtime/profiles -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  cp -a "${RESTORE_TMP}/bridge/profiles/." host-browser-bridge/.runtime/profiles/
  host-browser-bridge/start.sh
fi
docker compose up -d
echo "正式恢复已完成，请执行：bash scripts/verify-local.sh"
