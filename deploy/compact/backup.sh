#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${compact_directory}/../.." && pwd)"
backup_directory="${1:-}"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

if [[ -z "${backup_directory}" || "${backup_directory}" != /* ]]; then
  echo "用法: $0 /绝对路径/新备份目录" >&2
  exit 2
fi
if [[ -e "${backup_directory}" || -L "${backup_directory}" ]]; then
  echo "拒绝覆盖已有备份路径: ${backup_directory}" >&2
  exit 2
fi
compact_source_environment
container_user="$(id -u):$(id -g)"
compact_compose config --quiet

umask 077
mkdir -p "${backup_directory}/minio"
chmod 700 "${backup_directory}"
services_stopped=0

restart_services() {
  if [[ "${services_stopped}" -eq 1 ]]; then
    compact_compose up --detach --wait backend worker frontend
    services_stopped=0
  fi
}
trap restart_services EXIT

compact_compose stop frontend worker backend
services_stopped=1
compact_compose exec -T postgres pg_dump \
  --username flowtest \
  --dbname flowtest \
  --format custom \
  --no-owner \
  --no-acl >"${backup_directory}/postgres.dump"
compact_compose run --rm --no-deps \
  --user "${container_user}" \
  --volume "${backup_directory}:/backup" \
  backend python -m app.operations.storage_transfer backup /backup/minio

if [[ -n "${FLOWTEST_BACKUP_SOURCE_REVISION_FILE:-}" ]]; then
  if [[ "${FLOWTEST_BACKUP_SOURCE_REVISION_FILE}" != /* ||
    ! -f "${FLOWTEST_BACKUP_SOURCE_REVISION_FILE}" ||
    -L "${FLOWTEST_BACKUP_SOURCE_REVISION_FILE}" ]]; then
    echo "备份源码版本文件必须是绝对路径普通文件" >&2
    exit 2
  fi
  cp "${FLOWTEST_BACKUP_SOURCE_REVISION_FILE}" "${backup_directory}/source-revision"
elif command -v git >/dev/null 2>&1 &&
  git -C "${repository_root}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "${repository_root}" rev-parse HEAD >"${backup_directory}/source-revision"
elif [[ -f "${repository_root}/SOURCE_REVISION" ]]; then
  cp "${repository_root}/SOURCE_REVISION" "${backup_directory}/source-revision"
fi
restart_services
trap - EXIT
echo "Compact 一致性备份已完成: ${backup_directory}"
