#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backup_directory="${1:-}"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

if [[ "${FLOWTEST_RESTORE_CONFIRM:-}" != "RESTORE" ]]; then
  echo "恢复会覆盖 Compact PostgreSQL 与 MinIO。请设置 FLOWTEST_RESTORE_CONFIRM=RESTORE。" >&2
  exit 2
fi
if [[ -z "${backup_directory}" || "${backup_directory}" != /* ]]; then
  echo "用法: FLOWTEST_RESTORE_CONFIRM=RESTORE $0 /绝对路径/备份目录" >&2
  exit 2
fi
test -f "${backup_directory}/postgres.dump"
test -f "${backup_directory}/minio/manifest.json"

compact_source_environment
container_user="$(id -u):$(id -g)"
compact_compose config --quiet

# 覆盖任何当前数据之前，完整验证数据库 Dump 与每个 Artifact 的大小和 SHA-256。
compact_compose exec -T postgres pg_restore --list <"${backup_directory}/postgres.dump" >/dev/null
compact_compose run --rm --no-deps \
  --user "${container_user}" \
  --volume "${backup_directory}:/backup:ro" \
  backend python -m app.operations.storage_transfer validate /backup/minio

compact_compose stop frontend worker backend
compact_compose exec -T postgres dropdb --force --if-exists \
  --username flowtest flowtest
compact_compose exec -T postgres createdb --username flowtest flowtest
compact_compose exec -T postgres pg_restore \
  --username flowtest \
  --dbname flowtest \
  --no-owner \
  --no-acl <"${backup_directory}/postgres.dump"
compact_compose run --rm --no-deps \
  --user "${container_user}" \
  --volume "${backup_directory}:/backup:ro" \
  backend python -m app.operations.storage_transfer restore /backup/minio --replace
compact_compose run --rm --no-deps \
  --user "${container_user}" \
  --volume "${backup_directory}:/backup:ro" \
  backend python -m app.operations.storage_transfer verify /backup/minio
compact_compose up --detach --wait backend worker frontend
"${compact_directory}/verify.sh" "${environment_file}"
echo "Compact 备份已恢复并通过哈希与 Readiness 验证"
