#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
evidence_file="${1:-}"
duration_seconds="${FLOWTEST_S34_SOAK_DURATION_SECONDS:-300}"
interval_seconds="${FLOWTEST_S34_SOAK_INTERVAL_SECONDS:-5}"
allowed_failures="${FLOWTEST_S34_SOAK_ALLOWED_FAILURES:-0}"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

if [[ -z "${evidence_file}" || "${evidence_file}" != /* ]]; then
  echo "用法: $0 /绝对路径/新稳定性证据.json" >&2
  exit 2
fi
if [[ -e "${evidence_file}" || -L "${evidence_file}" ]]; then
  echo "拒绝覆盖已有证据: ${evidence_file}" >&2
  exit 2
fi
if [[ ! "${duration_seconds}" =~ ^[0-9]+$ || "${duration_seconds}" -lt 10 ]]; then
  echo "稳定性观察时长不得少于 10 秒" >&2
  exit 2
fi
if [[ ! "${interval_seconds}" =~ ^[0-9]+$ || "${interval_seconds}" -lt 1 || "${interval_seconds}" -gt 60 ]]; then
  echo "探测间隔必须在 1～60 秒之间" >&2
  exit 2
fi

compact_source_environment
"${compact_directory}/verify.sh" "${environment_file}"
base_url="http://127.0.0.1:${FLOWTEST_HTTP_PORT:-3000}/api/v1"
latency_file="$(mktemp)"
trap 'rm -f "${latency_file}"' EXIT

container_ids=()
while IFS= read -r container_id; do
  container_ids+=("${container_id}")
done < <(compact_compose ps -q)
restart_count_before=0
for container_id in "${container_ids[@]}"; do
  restart_count_before=$((restart_count_before + $(docker inspect "${container_id}" --format '{{.RestartCount}}')))
done

started_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
started_seconds="${SECONDS}"
samples=0
failures=0
consecutive_failures=0
maximum_consecutive_failures=0
while [[ $((SECONDS - started_seconds)) -lt "${duration_seconds}" ]]; do
  samples=$((samples + 1))
  probe_result="$(curl --silent --output /dev/null --write-out '%{http_code} %{time_total}' "${base_url}/ready" || true)"
  http_status="${probe_result%% *}"
  latency_seconds="${probe_result#* }"
  runtime_profile="$(curl --silent --fail "${base_url}/runtime-profile" || true)"
  running_services="$(compact_compose ps --services --status running | awk 'NF {count += 1} END {print count + 0}')"
  if [[ "${http_status}" == "200" && "${runtime_profile}" == *'"profile":"compact"'* && "${running_services}" -eq 6 ]]; then
    printf '%s\n' "${latency_seconds}" >>"${latency_file}"
    consecutive_failures=0
  else
    failures=$((failures + 1))
    consecutive_failures=$((consecutive_failures + 1))
    if [[ "${consecutive_failures}" -gt "${maximum_consecutive_failures}" ]]; then
      maximum_consecutive_failures="${consecutive_failures}"
    fi
  fi
  sleep "${interval_seconds}"
done

restart_count_after=0
for container_id in "${container_ids[@]}"; do
  restart_count_after=$((restart_count_after + $(docker inspect "${container_id}" --format '{{.RestartCount}}')))
done
successful_samples=$((samples - failures))
if [[ "${successful_samples}" -gt 0 ]]; then
  p95_row=$(((successful_samples * 95 + 99) / 100))
  p95_seconds="$(LC_ALL=C sort -n "${latency_file}" | awk -v row="${p95_row}" 'NR == row {print; exit}')"
else
  p95_seconds=0
fi

queue_total=0
for queue_name in general celery data ai performance environment; do
  queue_depth="$(compact_compose exec -T redis redis-cli -n 1 LLEN "${queue_name}" | tr -d '\r')"
  queue_total=$((queue_total + queue_depth))
done
finished_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
status="passed"
if [[ "${failures}" -gt "${allowed_failures}" || "${restart_count_after}" -ne "${restart_count_before}" || "${queue_total}" -ne 0 ]]; then
  status="failed"
fi

mkdir -p "$(dirname "${evidence_file}")"
printf '{"status":"%s","started_at":"%s","finished_at":"%s","duration_seconds":%s,"samples":%s,"failures":%s,"maximum_consecutive_failures":%s,"p95_ready_seconds":%s,"restart_count_before":%s,"restart_count_after":%s,"queued_tasks":%s}\n' \
  "${status}" "${started_at}" "${finished_at}" "${duration_seconds}" "${samples}" "${failures}" \
  "${maximum_consecutive_failures}" "${p95_seconds}" "${restart_count_before}" \
  "${restart_count_after}" "${queue_total}" >"${evidence_file}"
trap - EXIT
rm -f "${latency_file}"
if [[ "${status}" != "passed" ]]; then
  echo "Compact 稳定性观察失败: ${evidence_file}" >&2
  exit 1
fi
echo "Compact 稳定性观察通过: ${evidence_file}"
