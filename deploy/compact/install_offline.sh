#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bundle_directory="$(cd "${compact_directory}/../.." && pwd)"
load_only=0
if [[ "${1:-}" == "--load-only" ]]; then
  load_only=1
elif [[ -n "${1:-}" ]]; then
  echo "用法: $0 [--load-only]" >&2
  exit 2
fi
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

for command_name in docker openssl awk sed; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "离线安装失败：缺少 ${command_name}" >&2
    exit 2
  fi
done
for required_file in images.tar images.manifest SHA256SUMS VERSION SOURCE_REVISION SOURCE_STATE; do
  if [[ ! -f "${bundle_directory}/${required_file}" ]]; then
    echo "离线包不完整：缺少 ${required_file}" >&2
    exit 2
  fi
done
source_state="$(sed -n '1p' "${bundle_directory}/SOURCE_STATE")"
if [[ "${source_state}" != "clean" && "${source_state}" != "dirty" ]]; then
  echo "离线包 SOURCE_STATE 非法" >&2
  exit 1
fi
if [[ "${source_state}" == "dirty" && "${FLOWTEST_ALLOW_DIRTY_RELEASE:-0}" != "1" ]]; then
  echo "拒绝安装由未提交源码生成的 dirty 制品" >&2
  exit 1
fi

while read -r expected_hash relative_path; do
  if [[ -z "${expected_hash}" || -z "${relative_path}" || "${relative_path}" == /* || "${relative_path}" == *..* ]]; then
    echo "非法的离线包校验项: ${relative_path:-<empty>}" >&2
    exit 1
  fi
  actual_hash="$(compact_sha256 "${bundle_directory}/${relative_path}")"
  if [[ "${actual_hash}" != "${expected_hash}" ]]; then
    echo "离线包文件校验失败: ${relative_path}" >&2
    exit 1
  fi
done <"${bundle_directory}/SHA256SUMS"

docker image load --input "${bundle_directory}/images.tar" >/dev/null
expected_architecture=""
manifest_entries=0
seen_variables="|"
while IFS=$'\t' read -r variable_name image_reference expected_id image_os image_architecture; do
  case "${variable_name}" in
    FLOWTEST_BACKEND_IMAGE | FLOWTEST_FRONTEND_IMAGE | FLOWTEST_POSTGRES_IMAGE | FLOWTEST_REDIS_IMAGE | FLOWTEST_MINIO_IMAGE) ;;
    *)
      echo "镜像清单含未知变量: ${variable_name}" >&2
      exit 1
      ;;
  esac
  if [[ "${seen_variables}" == *"|${variable_name}|"* || "${image_os}" != "linux" ]]; then
    echo "镜像清单格式错误" >&2
    exit 1
  fi
  seen_variables="${seen_variables}${variable_name}|"
  manifest_entries=$((manifest_entries + 1))
  actual_id="$(docker image inspect "${image_reference}" --format '{{.Id}}')"
  actual_architecture="$(docker image inspect "${image_reference}" --format '{{.Architecture}}')"
  actual_architecture="$(compact_normalize_architecture "${actual_architecture}")"
  if [[ "${actual_id}" != "${expected_id}" || "${actual_architecture}" != "${image_architecture}" ]]; then
    echo "镜像与清单不一致: ${image_reference}" >&2
    exit 1
  fi
  if [[ -n "${expected_architecture}" && "${expected_architecture}" != "${image_architecture}" ]]; then
    echo "离线包中混入了不同架构的镜像" >&2
    exit 1
  fi
  expected_architecture="${image_architecture}"
done <"${bundle_directory}/images.manifest"
if [[ "${manifest_entries}" -ne 5 ]]; then
  echo "镜像清单必须恰好包含 5 个唯一镜像" >&2
  exit 1
fi

docker_architecture="$(compact_normalize_architecture "$(docker info --format '{{.Architecture}}')")"
if [[ "${docker_architecture}" != "${expected_architecture}" ]]; then
  echo "离线包架构为 ${expected_architecture}，当前 Docker 为 ${docker_architecture}" >&2
  exit 1
fi

echo "Compact 离线镜像已导入并通过 ID/架构校验"
if [[ "${load_only}" -eq 0 ]]; then
  "${compact_directory}/start_offline.sh"
fi
