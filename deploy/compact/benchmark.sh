#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${compact_directory}/../.." && pwd)"
evidence_file="${1:-}"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

if [[ -z "${evidence_file}" || "${evidence_file}" != /* ]]; then
  echo "用法: $0 /绝对路径/新资源基线.json" >&2
  exit 2
fi
if [[ -e "${evidence_file}" || -L "${evidence_file}" ]]; then
  echo "拒绝覆盖已有证据: ${evidence_file}" >&2
  exit 2
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "容量基线需要源码工作站安装 uv" >&2
  exit 2
fi

compact_source_environment
"${compact_directory}/verify.sh" "${environment_file}"

docker_stats_json() {
  local container_ids=()
  while IFS= read -r container_id; do
    container_ids+=("${container_id}")
  done < <(compact_compose ps -q)
  docker stats --no-stream --format '{{json .}}' "${container_ids[@]}" \
    | awk 'BEGIN {printf "["} {if (NR > 1) printf ","; printf "%s", $0} END {printf "]"}'
}

queue_depths_json() {
  local first=1
  local queue_name
  local queue_depth
  printf '{'
  for queue_name in general celery data ai performance environment; do
    queue_depth="$(compact_compose exec -T redis redis-cli -n 1 LLEN "${queue_name}" | tr -d '\r')"
    if [[ "${first}" -eq 0 ]]; then
      printf ','
    fi
    printf '"%s":%s' "${queue_name}" "${queue_depth}"
    first=0
  done
  printf '}'
}

stats_before="$(docker_stats_json)"
api_result="$(
  FLOWTEST_API_URL="http://127.0.0.1:${FLOWTEST_HTTP_PORT:-3000}/api/v1" \
  FLOWTEST_CAPACITY_REQUESTS="${FLOWTEST_S34_API_REQUESTS:-1000}" \
  FLOWTEST_CAPACITY_CONCURRENCY="${FLOWTEST_S34_API_CONCURRENCY:-25}" \
  FLOWTEST_CAPACITY_P95_SECONDS="${FLOWTEST_S34_API_P95_SECONDS:-0.5}" \
    uv run --project "${repository_root}/backend" python "${repository_root}/scripts/capacity_s11.py"
)"
workflow_result="$(
  FLOWTEST_SMOKE_API_URL="http://127.0.0.1:${FLOWTEST_HTTP_PORT:-3000}/api/v1" \
  FLOWTEST_SMOKE_ADMIN_EMAIL="${FLOWTEST_BOOTSTRAP_ADMIN_EMAIL}" \
  FLOWTEST_SMOKE_ADMIN_PASSWORD="${FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD}" \
  FLOWTEST_SMOKE_TARGET_URL=http://backend:8000/api/v1 \
  FLOWTEST_CAPACITY_WORKFLOW_REQUESTS="${FLOWTEST_S34_WORKFLOW_REQUESTS:-24}" \
  FLOWTEST_CAPACITY_WORKFLOW_CONCURRENCY="${FLOWTEST_S34_WORKFLOW_CONCURRENCY:-6}" \
  FLOWTEST_CAPACITY_WORKFLOW_P95_SECONDS="${FLOWTEST_S34_WORKFLOW_P95_SECONDS:-15}" \
    uv run --project "${repository_root}/backend" python "${repository_root}/scripts/capacity_workflow.py"
)"
stats_after="$(docker_stats_json)"
queue_depths="$(queue_depths_json)"

mkdir -p "$(dirname "${evidence_file}")"
printf '{"status":"passed","profile":"compact","api":%s,"workflow":%s,"queues":%s,"stats_before":%s,"stats_after":%s}\n' \
  "${api_result}" "${workflow_result}" "${queue_depths}" "${stats_before}" "${stats_after}" \
  >"${evidence_file}"
echo "Compact 资源与工作流容量基线通过: ${evidence_file}"
