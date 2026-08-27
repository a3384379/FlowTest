#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
registry_prefix="${1:-}"
release_version="${2:-}"
output_environment="${3:-}"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

if [[ ! "${registry_prefix}" =~ ^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9]+([._-][a-z0-9]+)*)+$ ]]; then
  echo "私有仓库前缀应形如 registry.example.com/team/flowtest，不含协议和末尾斜线" >&2
  exit 2
fi
if [[ ! "${release_version}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
  echo "版本只能包含字母、数字、点、下划线和短横线" >&2
  exit 2
fi
if [[ -z "${output_environment}" || "${output_environment}" != /* ]]; then
  echo "用法: $0 registry.example.com/team/flowtest 4.0.0 /绝对路径/images.env" >&2
  exit 2
fi
if [[ -e "${output_environment}" || -L "${output_environment}" ]]; then
  echo "拒绝覆盖已有镜像配置: ${output_environment}" >&2
  exit 2
fi

repository_root="$(cd "${compact_directory}/../.." && pwd)"
compact_require_clean_source "${repository_root}"

if [[ ! -f "${environment_file}" ]]; then
  "${compact_directory}/generate_env.sh" "${environment_file}"
fi
compact_source_environment
"${compact_directory}/preflight.sh" "${environment_file}"
if [[ ! -f "${image_environment_file}" ]]; then
  compact_compose_build build backend frontend
fi
docker_architecture="$(docker info --format '{{.Architecture}}')"
architecture="$(compact_normalize_architecture "${docker_architecture}")" || {
  echo "不支持 Docker 架构: ${docker_architecture}" >&2
  exit 1
}

mkdir -p "$(dirname "${output_environment}")"
temporary_output="$(mktemp "${output_environment}.tmp.XXXXXX")"
trap 'rm -f "${temporary_output}"' EXIT
printf '# FlowTest Compact %s immutable private-registry images\n' "${release_version}" \
  >"${temporary_output}"
printf '# Source revision: %s\n' "$(git -C "${repository_root}" rev-parse HEAD)" \
  >>"${temporary_output}"
if [[ -n "$(git -C "${repository_root}" status --porcelain --untracked-files=normal)" ]]; then
  printf '# Source state: dirty\n' >>"${temporary_output}"
else
  printf '# Source state: clean\n' >>"${temporary_output}"
fi
printf '# Platform: linux/%s\n' "${architecture}" >>"${temporary_output}"

publish_image() {
  local variable_name="$1"
  local logical_name="$2"
  local source_reference="$3"
  local target_repository="${registry_prefix}/${logical_name}"
  local target_reference="${target_repository}:${release_version}-${architecture}"
  local immutable_reference=""

  if ! docker image inspect "${source_reference}" >/dev/null 2>&1; then
    docker image pull "${source_reference}"
  fi
  docker image tag "${source_reference}" "${target_reference}"
  docker image push "${target_reference}"
  while IFS= read -r repository_digest; do
    case "${repository_digest}" in
      "${target_repository}"@sha256:*) immutable_reference="${repository_digest}" ;;
    esac
  done < <(docker image inspect "${target_reference}" --format '{{range .RepoDigests}}{{println .}}{{end}}')
  if [[ -z "${immutable_reference}" ]]; then
    echo "推送后未获得私有仓库摘要: ${target_reference}" >&2
    exit 1
  fi
  printf '%s=%s\n' "${variable_name}" "${immutable_reference}" >>"${temporary_output}"
}

publish_image FLOWTEST_BACKEND_IMAGE flowtest-backend \
  "${FLOWTEST_BACKEND_IMAGE:-flowtest/backend:local}"
publish_image FLOWTEST_FRONTEND_IMAGE flowtest-frontend \
  "${FLOWTEST_FRONTEND_IMAGE:-flowtest/frontend:local}"
publish_image FLOWTEST_POSTGRES_IMAGE postgres \
  "${FLOWTEST_POSTGRES_IMAGE:-postgres:17.6-alpine}"
publish_image FLOWTEST_REDIS_IMAGE redis \
  "${FLOWTEST_REDIS_IMAGE:-redis:8.2.1-alpine}"
publish_image FLOWTEST_MINIO_IMAGE minio \
  "${FLOWTEST_MINIO_IMAGE:-minio/minio:RELEASE.2025-07-23T15-54-02Z}"

chmod 0644 "${temporary_output}"
mv "${temporary_output}" "${output_environment}"
trap - EXIT
echo "私有仓库镜像已推送，不可变摘要已写入: ${output_environment}"
