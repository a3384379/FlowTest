#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

if [[ ! -f "${environment_file}" ]]; then
  "${compact_directory}/generate_env.sh" "${environment_file}"
fi
if [[ -f "${image_environment_file}" ]]; then
  echo "检测到镜像配置，按无构建模式启动 Compact"
  exec "${compact_directory}/start_offline.sh"
fi

compact_source_environment
"${compact_directory}/preflight.sh" "${environment_file}"
compact_compose_build pull --policy missing postgres redis minio
compact_compose_build build backend frontend
compact_compose_build up --detach --no-build --pull never --wait
"${compact_directory}/verify.sh" "${environment_file}"
