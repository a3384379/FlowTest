#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${compact_directory}/../.." && pwd)"
output_archive="${1:-}"
bundle_version="${2:-s33}"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

if [[ -z "${output_archive}" || "${output_archive}" != /* ]]; then
  echo "用法: $0 /绝对路径/flowtest-compact.tar.gz [版本]" >&2
  exit 2
fi
if [[ -e "${output_archive}" || -L "${output_archive}" || -e "${output_archive}.sha256" ]]; then
  echo "拒绝覆盖已有离线包或摘要: ${output_archive}" >&2
  exit 2
fi
if [[ ! "${bundle_version}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
  echo "版本只能包含字母、数字、点、下划线和短横线" >&2
  exit 2
fi
if ! command -v git >/dev/null 2>&1; then
  echo "生成离线发布包需要 Git 记录源码版本" >&2
  exit 2
fi
compact_require_clean_source "${repository_root}"

if [[ ! -f "${environment_file}" ]]; then
  "${compact_directory}/generate_env.sh" "${environment_file}"
fi
compact_source_environment
"${compact_directory}/preflight.sh" "${environment_file}"

if [[ ! -f "${image_environment_file}" ]]; then
  compact_compose_build build backend frontend
fi

backend_source="${FLOWTEST_BACKEND_IMAGE:-flowtest/backend:local}"
frontend_source="${FLOWTEST_FRONTEND_IMAGE:-flowtest/frontend:local}"
postgres_source="${FLOWTEST_POSTGRES_IMAGE:-postgres:17.6-alpine}"
redis_source="${FLOWTEST_REDIS_IMAGE:-redis:8.2.1-alpine}"
minio_source="${FLOWTEST_MINIO_IMAGE:-minio/minio:RELEASE.2025-07-23T15-54-02Z}"

for image_reference in \
  "${backend_source}" \
  "${frontend_source}" \
  "${postgres_source}" \
  "${redis_source}" \
  "${minio_source}"; do
  if ! docker image inspect "${image_reference}" >/dev/null 2>&1; then
    docker image pull "${image_reference}"
  fi
done

docker_architecture="$(docker info --format '{{.Architecture}}')"
architecture="$(compact_normalize_architecture "${docker_architecture}")" || {
  echo "不支持 Docker 架构: ${docker_architecture}" >&2
  exit 1
}
bundle_root_name="flowtest-compact-${bundle_version}-${architecture}"
temporary_directory="$(mktemp -d)"
bundle_root="${temporary_directory}/${bundle_root_name}"
trap 'rm -rf "${temporary_directory}"' EXIT
mkdir -p "${bundle_root}/deploy/compact"

manifest="${bundle_root}/images.manifest"
image_environment="${bundle_root}/deploy/compact/images.env"
: >"${manifest}"
: >"${image_environment}"

append_image() {
  local variable_name="$1"
  local logical_name="$2"
  local source_reference="$3"
  local offline_reference="flowtest/offline-${logical_name}:${bundle_version}-${architecture}"
  local image_id
  local image_os
  local image_architecture

  docker image tag "${source_reference}" "${offline_reference}"
  image_id="$(docker image inspect "${offline_reference}" --format '{{.Id}}')"
  image_os="$(docker image inspect "${offline_reference}" --format '{{.Os}}')"
  image_architecture="$(docker image inspect "${offline_reference}" --format '{{.Architecture}}')"
  image_architecture="$(compact_normalize_architecture "${image_architecture}")"
  if [[ "${image_os}/${image_architecture}" != "linux/${architecture}" ]]; then
    echo "镜像平台不一致: ${source_reference} 为 ${image_os}/${image_architecture}" >&2
    exit 1
  fi
  printf '%s\t%s\t%s\t%s\t%s\n' \
    "${variable_name}" "${offline_reference}" "${image_id}" "${image_os}" "${image_architecture}" \
    >>"${manifest}"
  printf '%s=%s\n' "${variable_name}" "${offline_reference}" >>"${image_environment}"
}

append_image FLOWTEST_BACKEND_IMAGE backend "${backend_source}"
append_image FLOWTEST_FRONTEND_IMAGE frontend "${frontend_source}"
append_image FLOWTEST_POSTGRES_IMAGE postgres "${postgres_source}"
append_image FLOWTEST_REDIS_IMAGE redis "${redis_source}"
append_image FLOWTEST_MINIO_IMAGE minio "${minio_source}"

offline_images=()
while IFS= read -r image_reference; do
  offline_images+=("${image_reference}")
done < <(awk -F '\t' '{print $2}' "${manifest}")
docker image save --output "${bundle_root}/images.tar" "${offline_images[@]}"

for deployment_file in \
  _lib.sh \
  backup.sh \
  collect_support_bundle.sh \
  compose.yaml \
  drill_rollback.sh \
  generate_env.sh \
  install_offline.sh \
  preflight.sh \
  restore.sh \
  rollback_probe.py \
  soak.sh \
  start_offline.sh \
  SUPPORT_BUNDLE_SCOPE.txt \
  upgrade_offline.sh \
  verify.sh \
  verify_support_bundle.sh; do
  cp -p "${compact_directory}/${deployment_file}" "${bundle_root}/deploy/compact/${deployment_file}"
done
cp -p "${compact_directory}/OFFLINE_README.md" "${bundle_root}/README.md"
printf '%s\n' "${bundle_version}" >"${bundle_root}/VERSION"
git -C "${repository_root}" rev-parse HEAD >"${bundle_root}/SOURCE_REVISION"
if [[ -n "$(git -C "${repository_root}" status --porcelain --untracked-files=normal)" ]]; then
  printf 'dirty\n' >"${bundle_root}/SOURCE_STATE"
else
  printf 'clean\n' >"${bundle_root}/SOURCE_STATE"
fi

checksum_manifest="${temporary_directory}/SHA256SUMS"
(
  cd "${bundle_root}"
  find . -type f ! -name SHA256SUMS -print | LC_ALL=C sort | while IFS= read -r relative_path; do
    printf '%s  %s\n' "$(compact_sha256 "${relative_path}")" "${relative_path#./}"
  done
) >"${checksum_manifest}"
mv "${checksum_manifest}" "${bundle_root}/SHA256SUMS"

mkdir -p "$(dirname "${output_archive}")"
tar -C "${temporary_directory}" -czf "${output_archive}" "${bundle_root_name}"
printf '%s  %s\n' "$(compact_sha256 "${output_archive}")" "$(basename "${output_archive}")" \
  >"${output_archive}.sha256"
echo "Compact 离线包已生成: ${output_archive}"
echo "平台: linux/${architecture}; 镜像: 5; 外部摘要: ${output_archive}.sha256"
