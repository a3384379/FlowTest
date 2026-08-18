#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
environment_file="${1:-${FLOWTEST_COMPACT_ENV_FILE:-${compact_directory}/.env}}"
mode="${2:-source}"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

for command_name in docker openssl curl awk sort df; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "安装前检查失败：缺少 ${command_name}" >&2
    exit 2
  fi
done
if ! docker info >/dev/null 2>&1; then
  echo "安装前检查失败：Docker Engine 不可用" >&2
  exit 2
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "安装前检查失败：需要 Docker Compose v2" >&2
  exit 2
fi

compose_version="$(docker compose version --short | sed 's/^v//')"
compose_major="${compose_version%%.*}"
if [[ ! "${compose_major}" =~ ^[0-9]+$ || "${compose_major}" -lt 2 ]]; then
  echo "安装前检查失败：需要 Docker Compose v2，当前 ${compose_version}" >&2
  exit 2
fi

compact_source_environment
compact_compose config --quiet
service_count="$(compact_compose config --services | awk 'NF {count += 1} END {print count + 0}')"
if [[ "${service_count}" -ne 6 ]]; then
  echo "安装前检查失败：Compact 必须恰好包含 6 个服务" >&2
  exit 1
fi

docker_platform="$(docker info --format '{{.OSType}}/{{.Architecture}}')"
case "${docker_platform}" in
  linux/amd64 | linux/x86_64 | linux/arm64 | linux/aarch64) ;;
  *)
    echo "安装前检查失败：不支持 Docker 平台 ${docker_platform}" >&2
    exit 1
    ;;
esac

memory_bytes="$(docker info --format '{{.MemTotal}}')"
minimum_memory_bytes=$((3 * 1024 * 1024 * 1024))
if [[ "${memory_bytes}" -lt "${minimum_memory_bytes}" ]]; then
  echo "安装前检查失败：Docker 可用内存少于 3 GiB" >&2
  exit 1
fi
if [[ "${memory_bytes}" -lt $((4 * 1024 * 1024 * 1024)) ]]; then
  echo "警告：Docker 可用内存低于建议的 4 GiB" >&2
fi

available_kib="$(df -Pk "${compact_directory}" | awk 'NR == 2 {print $4}')"
if [[ -n "${available_kib}" && "${available_kib}" -lt $((5 * 1024 * 1024)) ]]; then
  echo "安装前检查失败：当前磁盘可用空间少于 5 GiB" >&2
  exit 1
fi

if [[ "${mode}" == "offline" ]]; then
  image_references=()
  while IFS= read -r image_reference; do
    image_references+=("${image_reference}")
  done < <(compact_compose config --images | sort -u)
  if [[ "${#image_references[@]}" -ne 5 ]]; then
    echo "离线检查失败：预期 5 个唯一镜像，实际为 ${#image_references[@]}" >&2
    exit 1
  fi
  for image_reference in "${image_references[@]}"; do
    if ! docker image inspect "${image_reference}" >/dev/null 2>&1; then
      echo "离线检查失败：本机缺少镜像 ${image_reference}" >&2
      exit 1
    fi
  done
fi

echo "Compact 安装前检查通过: ${docker_platform}, Compose ${compose_version}, 6 服务"
