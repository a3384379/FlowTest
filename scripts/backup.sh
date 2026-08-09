#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backup_directory="${1:-}"
if [[ -z "${backup_directory}" ]]; then
  echo "用法: $0 /absolute/path/to/backup-directory" >&2
  exit 2
fi
if [[ "${backup_directory}" != /* ]]; then
  echo "备份目录必须是绝对路径" >&2
  exit 2
fi

mkdir -p "${backup_directory}/minio"
chmod 700 "${backup_directory}"
postgres_user="${POSTGRES_USER:-flowtest}"
postgres_database="${POSTGRES_DB:-flowtest}"

cd "${repository_root}"
docker compose exec -T postgres pg_dump \
  --username "${postgres_user}" \
  --dbname "${postgres_database}" \
  --format custom \
  --no-owner \
  --no-acl > "${backup_directory}/postgres.dump"

FLOWTEST_S3_ENDPOINT_URL="${FLOWTEST_S3_ENDPOINT_URL:-http://localhost:9000}" \
FLOWTEST_S3_ACCESS_KEY="${FLOWTEST_S3_ACCESS_KEY:-${MINIO_ROOT_USER:-flowtest}}" \
FLOWTEST_S3_SECRET_KEY="${FLOWTEST_S3_SECRET_KEY:-${MINIO_ROOT_PASSWORD:-flowtest-local-secret}}" \
  uv run --project backend --locked python scripts/storage_transfer.py backup "${backup_directory}/minio"

git rev-parse HEAD > "${backup_directory}/source-revision"
echo "备份完成: ${backup_directory}"
