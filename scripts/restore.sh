#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backup_directory="${1:-}"
if [[ "${FLOWTEST_RESTORE_CONFIRM:-}" != "RESTORE" ]]; then
  echo "恢复会覆盖当前 PostgreSQL 数据库与 MinIO Bucket。请设置 FLOWTEST_RESTORE_CONFIRM=RESTORE。" >&2
  exit 2
fi
if [[ -z "${backup_directory}" || "${backup_directory}" != /* ]]; then
  echo "恢复目录必须是绝对路径" >&2
  exit 2
fi
test -f "${backup_directory}/postgres.dump"
test -f "${backup_directory}/minio/manifest.json"

postgres_user="${POSTGRES_USER:-flowtest}"
postgres_database="${POSTGRES_DB:-flowtest}"
cd "${repository_root}"
docker compose stop backend worker beat
docker compose exec -T postgres dropdb --force --if-exists \
  --username "${postgres_user}" "${postgres_database}"
docker compose exec -T postgres createdb --username "${postgres_user}" "${postgres_database}"
docker compose exec -T postgres pg_restore \
  --username "${postgres_user}" \
  --dbname "${postgres_database}" \
  --no-owner \
  --no-acl < "${backup_directory}/postgres.dump"

FLOWTEST_S3_ENDPOINT_URL="${FLOWTEST_S3_ENDPOINT_URL:-http://localhost:9000}" \
FLOWTEST_S3_ACCESS_KEY="${FLOWTEST_S3_ACCESS_KEY:-${MINIO_ROOT_USER:-flowtest}}" \
FLOWTEST_S3_SECRET_KEY="${FLOWTEST_S3_SECRET_KEY:-${MINIO_ROOT_PASSWORD:-flowtest-local-secret}}" \
  uv run --project backend --locked python scripts/storage_transfer.py restore \
    "${backup_directory}/minio" --replace
docker compose up -d --wait backend worker beat frontend
echo "恢复完成，并已通过 Compose 健康检查"
