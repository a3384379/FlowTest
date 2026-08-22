#!/usr/bin/env bash

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
environment_file="${environment_file:-${FLOWTEST_COMPACT_ENV_FILE:-${compact_directory}/.env}}"
image_environment_file="${image_environment_file:-${FLOWTEST_COMPACT_IMAGE_ENV_FILE:-${compact_directory}/images.env}}"

compact_require_environment() {
  if [[ ! -f "${environment_file}" ]]; then
    echo "找不到 Compact 配置: ${environment_file}" >&2
    return 2
  fi
  if [[ -n "${FLOWTEST_COMPACT_IMAGE_ENV_FILE:-}" && ! -f "${image_environment_file}" ]]; then
    echo "找不到指定的镜像配置: ${image_environment_file}" >&2
    return 2
  fi
}

compact_source_environment() {
  compact_require_environment
  set -a
  # shellcheck disable=SC1090
  source "${environment_file}"
  if [[ -f "${image_environment_file}" ]]; then
    # shellcheck disable=SC1090
    source "${image_environment_file}"
  fi
  set +a
}

compact_compose() {
  local arguments=(docker compose --env-file "${environment_file}")
  if [[ -f "${image_environment_file}" ]]; then
    arguments+=(--env-file "${image_environment_file}")
  fi
  arguments+=(--file "${compact_directory}/compose.yaml")
  "${arguments[@]}" "$@"
}

compact_compose_build() {
  local arguments=(docker compose --env-file "${environment_file}")
  if [[ -f "${image_environment_file}" ]]; then
    arguments+=(--env-file "${image_environment_file}")
  fi
  arguments+=(
    --file "${compact_directory}/compose.yaml"
    --file "${compact_directory}/compose.build.yaml"
  )
  "${arguments[@]}" "$@"
}

compact_sha256() {
  openssl dgst -sha256 "$1" | awk '{print $NF}'
}

compact_normalize_architecture() {
  case "$1" in
    amd64 | x86_64) echo "amd64" ;;
    arm64 | aarch64) echo "arm64" ;;
    *) return 1 ;;
  esac
}

compact_require_clean_source() {
  local repository_root="$1"
  if [[ -n "$(git -C "${repository_root}" status --porcelain --untracked-files=normal)" ]]; then
    if [[ "${FLOWTEST_ALLOW_DIRTY_RELEASE:-0}" != "1" ]]; then
      echo "拒绝从含未提交变更的源码生成发布制品" >&2
      return 1
    fi
    echo "警告：正在生成仅供开发验收的 dirty 制品" >&2
  fi
}
