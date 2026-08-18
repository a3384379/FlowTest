#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
environment_file="${1:-${FLOWTEST_COMPACT_ENV_FILE:-${compact_directory}/.env}}"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"
compact_source_environment
compact_compose config --quiet

running_count="$(compact_compose ps --services --status running | awk 'NF {count += 1} END {print count + 0}')"
if [[ "${running_count}" -ne 6 ]]; then
  echo "预期 6 个运行中服务，实际为 ${running_count}" >&2
  compact_compose ps >&2
  exit 1
fi

base_url="http://127.0.0.1:${FLOWTEST_HTTP_PORT:-3000}/api/v1"
readiness="$(curl --fail --silent --show-error "${base_url}/ready")"
runtime_profile="$(curl --fail --silent --show-error "${base_url}/runtime-profile")"

if [[ "${readiness}" != *'"status":"ok"'* ]]; then
  echo "就绪检查未通过: ${readiness}" >&2
  exit 1
fi
if [[ "${runtime_profile}" != *'"profile":"compact"'* ]]; then
  echo "运行档位不正确: ${runtime_profile}" >&2
  exit 1
fi

echo "Compact 验收通过: 6 个服务运行中，数据库、Redis 和对象存储均就绪"
