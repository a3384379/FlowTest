#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backup_directory="${1:-}"
evidence_file="${2:-}"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

if [[ -z "${backup_directory}" || "${backup_directory}" != /* ]]; then
  echo "用法: $0 /绝对路径/新备份目录 /绝对路径/新回滚证据.json" >&2
  exit 2
fi
if [[ -z "${evidence_file}" || "${evidence_file}" != /* ]]; then
  echo "用法: $0 /绝对路径/新备份目录 /绝对路径/新回滚证据.json" >&2
  exit 2
fi
if [[ -e "${backup_directory}" || -L "${backup_directory}" ]]; then
  echo "拒绝覆盖已有演练备份: ${backup_directory}" >&2
  exit 2
fi
if [[ -e "${evidence_file}" || -L "${evidence_file}" ]]; then
  echo "拒绝覆盖已有回滚证据: ${evidence_file}" >&2
  exit 2
fi

compact_source_environment
compact_compose config --quiet
"${compact_directory}/verify.sh" "${environment_file}"

umask 077
temporary_directory="$(mktemp -d)"
recovery_required=0

restore_baseline() {
  FLOWTEST_RESTORE_CONFIRM=RESTORE \
    "${compact_directory}/restore.sh" "${backup_directory}"
}

cleanup() {
  local original_status=$?
  if [[ "${recovery_required}" -eq 1 ]]; then
    recovery_required=0
    echo "演练中断，正在尝试恢复演练前基线" >&2
    if ! restore_baseline; then
      echo "自动恢复失败，请立即使用保留的备份手工恢复: ${backup_directory}" >&2
    fi
  fi
  rm -rf "${temporary_directory}"
  exit "${original_status}"
}
trap cleanup EXIT

run_probe() {
  compact_compose run --rm --no-deps \
    --env FLOWTEST_ROLLBACK_PROBE_API_URL=http://backend:8000/api/v1 \
    --volume "${compact_directory}/rollback_probe.py:/flowtest-rollback-probe.py:ro" \
    backend python /flowtest-rollback-probe.py "$@"
}

extract_project_id() {
  printf '%s\n' "$1" | sed -n 's/.*"project_id": *"\([0-9a-fA-F-]*\)".*/\1/p'
}

"${compact_directory}/backup.sh" "${backup_directory}"

recovery_required=1
mutation_result="$(run_probe create)"
mutation_project_id="$(extract_project_id "${mutation_result}")"
if [[ ! "${mutation_project_id}" =~ ^[0-9a-fA-F-]{36}$ ]]; then
  echo "未取得有效的回滚探针 Project ID" >&2
  exit 1
fi
restore_baseline
recovery_required=0
run_probe verify-absent --project-id "${mutation_project_id}" >"${temporary_directory}/first-absence.json"

recovery_required=1
post_restore_result="$(run_probe create)"
post_restore_project_id="$(extract_project_id "${post_restore_result}")"
if [[ ! "${post_restore_project_id}" =~ ^[0-9a-fA-F-]{36}$ ]]; then
  echo "恢复后未取得有效的写入探针 Project ID" >&2
  exit 1
fi
restore_baseline
recovery_required=0
run_probe verify-absent --project-id "${post_restore_project_id}" >"${temporary_directory}/second-absence.json"
"${compact_directory}/verify.sh" "${environment_file}"

mkdir -p "$(dirname "${evidence_file}")"
printf '{"schema_version":1,"status":"passed","completed_at_utc":"%s","rolled_back_mutation":%s,"post_restore_write":%s,"final_state":"baseline_restored"}\n' \
  "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
  "${mutation_result}" \
  "${post_restore_result}" >"${evidence_file}"

trap - EXIT
rm -rf "${temporary_directory}"
echo "Compact 备份、回滚、恢复后写入和最终基线恢复演练通过: ${evidence_file}"
echo "演练前一致性备份已保留: ${backup_directory}"
