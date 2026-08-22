#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

if [[ ! -f "${environment_file}" ]]; then
  "${compact_directory}/generate_env.sh" "${environment_file}"
fi
if [[ ! -f "${image_environment_file}" ]]; then
  echo "离线启动需要经过校验的镜像配置: ${image_environment_file}" >&2
  exit 2
fi

compact_source_environment
"${compact_directory}/preflight.sh" "${environment_file}" offline
compact_compose up --detach --no-build --pull never --wait
"${compact_directory}/verify.sh" "${environment_file}"
