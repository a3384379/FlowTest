#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${compact_directory}/../.." && pwd)"
compatibility_compose="${repository_root}/deploy/compatibility/compose.yaml"
evidence_file="${1:-}"
backup_directory="${FLOWTEST_S34_COMPATIBILITY_BACKUP_DIR:-${evidence_file}.backup}"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

if [[ -z "${evidence_file}" || "${evidence_file}" != /* ]]; then
  echo "用法: $0 /绝对路径/新兼容性证据.json" >&2
  exit 2
fi
if [[ -e "${evidence_file}" || -L "${evidence_file}" ]]; then
  echo "拒绝覆盖已有证据: ${evidence_file}" >&2
  exit 2
fi
if [[ -e "${backup_directory}" || -L "${backup_directory}" ]]; then
  echo "拒绝覆盖已有兼容演练备份: ${backup_directory}" >&2
  exit 2
fi

compact_source_environment
compatibility_arguments=(docker compose --env-file "${environment_file}")
if [[ -f "${image_environment_file}" ]]; then
  compatibility_arguments+=(--env-file "${image_environment_file}")
fi
compatibility_arguments+=(--file "${compatibility_compose}")
compatibility_compose_command() {
  "${compatibility_arguments[@]}" "$@"
}

temporary_directory="$(mktemp -d)"
compact_running=1
full_running=0
cleanup() {
  if [[ "${full_running}" -eq 1 ]]; then
    compatibility_compose_command down >/dev/null 2>&1 || true
  fi
  if [[ "${compact_running}" -eq 0 ]]; then
    compact_compose up --detach --no-build --pull never --wait >/dev/null 2>&1 || true
  fi
  rm -rf "${temporary_directory}"
}
trap cleanup EXIT

run_smoke() {
  FLOWTEST_SMOKE_API_URL="http://127.0.0.1:${FLOWTEST_HTTP_PORT:-3000}/api/v1" \
  FLOWTEST_SMOKE_ADMIN_EMAIL="${FLOWTEST_BOOTSTRAP_ADMIN_EMAIL}" \
  FLOWTEST_SMOKE_ADMIN_PASSWORD="${FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD}" \
  FLOWTEST_SMOKE_TARGET_URL=http://backend:8000/api/v1 \
    uv run --project "${repository_root}/backend" python "${repository_root}/scripts/smoke_s34.py" "$@"
}

read_evidence_ids() {
  uv run --project "${repository_root}/backend" python -c \
    'import json,sys; value=json.load(open(sys.argv[1])); print(value["project_id"], value["artifact_id"], value["workflow_execution_id"])' \
    "$1"
}

"${compact_directory}/verify.sh" "${environment_file}"
if [[ -f "${image_environment_file}" ]]; then
  FLOWTEST_COMPACT_ENV_FILE="${environment_file}" \
  FLOWTEST_COMPACT_IMAGE_ENV_FILE="${image_environment_file}" \
    "${compact_directory}/backup.sh" "${backup_directory}"
else
  FLOWTEST_COMPACT_ENV_FILE="${environment_file}" \
    "${compact_directory}/backup.sh" "${backup_directory}"
fi
run_smoke create --profile compact >"${temporary_directory}/compact.json"
read -r compact_project compact_artifact compact_execution \
  < <(read_evidence_ids "${temporary_directory}/compact.json")

compact_compose stop
compact_running=0
compatibility_compose_command up --detach --no-build --pull never --wait
full_running=1
run_smoke verify --profile full \
  --project-id "${compact_project}" \
  --artifact-id "${compact_artifact}" \
  --execution-id "${compact_execution}" >/dev/null
run_smoke create --profile full >"${temporary_directory}/full.json"
read -r full_project full_artifact full_execution \
  < <(read_evidence_ids "${temporary_directory}/full.json")

compatibility_compose_command down
full_running=0
compact_compose up --detach --no-build --pull never --wait
compact_running=1
"${compact_directory}/verify.sh" "${environment_file}"
run_smoke verify --profile compact \
  --project-id "${full_project}" \
  --artifact-id "${full_artifact}" \
  --execution-id "${full_execution}" >/dev/null

mkdir -p "$(dirname "${evidence_file}")"
printf '{"status":"passed","compact_created":%s,"full_created":%s}\n' \
  "$(cat "${temporary_directory}/compact.json")" \
  "$(cat "${temporary_directory}/full.json")" >"${evidence_file}"
trap - EXIT
rm -rf "${temporary_directory}"
echo "Full↔Compact 双向兼容验收通过: ${evidence_file}"
echo "演练前一致性备份: ${backup_directory}"
