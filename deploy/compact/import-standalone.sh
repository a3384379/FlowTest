#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bundle_directory="${1:-}"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

if [[ "${FLOWTEST_IMPORT_CONFIRM:-}" != "IMPORT_STANDALONE" ]]; then
  echo "导入会写入 Compact 数据库与 MinIO。请设置 FLOWTEST_IMPORT_CONFIRM=IMPORT_STANDALONE。" >&2
  exit 2
fi
if [[ -z "${bundle_directory}" || "${bundle_directory}" != /* ]]; then
  echo "用法: FLOWTEST_IMPORT_CONFIRM=IMPORT_STANDALONE $0 /绝对路径/transfer-bundle" >&2
  exit 2
fi
if [[ ! -d "${bundle_directory}" || -L "${bundle_directory}" || ! -f "${bundle_directory}/manifest.json" ]]; then
  echo "传输包必须是包含 manifest.json 的普通目录" >&2
  exit 2
fi

compact_source_environment
compact_compose config --quiet
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

container_user="$(id -u):$(id -g)"
compact_compose up --detach --wait postgres redis minio
compact_compose run --rm --no-deps backend alembic upgrade head
compact_compose run --rm --no-deps \
  --user "${container_user}" \
  --volume "${bundle_directory}:/transfer:ro" \
  backend python -m app.operations.standalone_transfer validate /transfer
compact_compose run --rm --no-deps \
  --user "${container_user}" \
  --volume "${bundle_directory}:/transfer:ro" \
  backend python -m app.operations.standalone_transfer import /transfer

compact_compose up --detach --wait backend worker frontend
services_stopped=0
trap - EXIT
"${compact_directory}/verify.sh" "${environment_file}"
echo "Standalone 数据已导入 Compact，并通过数据库、MinIO 与 Readiness 验证"
