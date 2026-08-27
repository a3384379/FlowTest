#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bundle_directory="$(cd "${compact_directory}/../.." && pwd)"
current_compact_directory_input="${1:-}"
backup_directory="${2:-}"
evidence_file="${3:-${backup_directory}.upgrade.json}"

if [[ -z "${current_compact_directory_input}" || "${current_compact_directory_input}" != /* ]]; then
  echo "用法: $0 /绝对路径/当前安装/deploy/compact /绝对路径/新备份目录 [/绝对路径/升级证据.json]" >&2
  exit 2
fi
if [[ ! -d "${current_compact_directory_input}" ]]; then
  echo "当前 Compact 安装目录不存在: ${current_compact_directory_input}" >&2
  exit 2
fi
current_compact_directory="$(cd "${current_compact_directory_input}" && pwd)"
current_bundle_directory="$(cd "${current_compact_directory}/../.." && pwd)"
if [[ -z "${backup_directory}" || "${backup_directory}" != /* || -e "${backup_directory}" || -L "${backup_directory}" ]]; then
  echo "升级备份必须是不存在的绝对路径" >&2
  exit 2
fi
if [[ -z "${evidence_file}" || "${evidence_file}" != /* || -e "${evidence_file}" || -L "${evidence_file}" ]]; then
  echo "升级证据必须是不存在的绝对路径" >&2
  exit 2
fi
if [[ "${FLOWTEST_S36_FORCE_POST_START_FAILURE:-0}" != "0" &&
  "${FLOWTEST_S36_FORCE_POST_START_FAILURE:-0}" != "1" ]]; then
  echo "FLOWTEST_S36_FORCE_POST_START_FAILURE 只能为 0 或 1" >&2
  exit 2
fi
for required_file in .env images.env compose.yaml restore.sh start_offline.sh verify.sh; do
  if [[ ! -f "${current_compact_directory}/${required_file}" ]]; then
    echo "当前安装不完整：缺少 ${required_file}" >&2
    exit 2
  fi
done
for metadata_file in VERSION SOURCE_REVISION SOURCE_STATE; do
  if [[ ! -f "${current_bundle_directory}/${metadata_file}" ]]; then
    echo "当前安装缺少版本元数据: ${metadata_file}" >&2
    exit 2
  fi
done
if [[ "${current_compact_directory}" != "${compact_directory}" &&
  ( -e "${compact_directory}/.env" || -L "${compact_directory}/.env" ) ]]; then
  echo "新版本目录已存在 .env，拒绝覆盖或混用部署凭据" >&2
  exit 2
fi

read_metadata() {
  local metadata_directory="$1"
  local metadata_name="$2"
  tr -d '\r\n' <"${metadata_directory}/${metadata_name}"
}

from_version="$(read_metadata "${current_bundle_directory}" VERSION)"
from_revision="$(read_metadata "${current_bundle_directory}" SOURCE_REVISION)"
from_source_state="$(read_metadata "${current_bundle_directory}" SOURCE_STATE)"
to_version="$(read_metadata "${bundle_directory}" VERSION)"
to_revision="$(read_metadata "${bundle_directory}" SOURCE_REVISION)"
to_source_state="$(read_metadata "${bundle_directory}" SOURCE_STATE)"
for version in "${from_version}" "${to_version}"; do
  if [[ ! "${version}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
    echo "离线安装版本元数据非法" >&2
    exit 2
  fi
done
for revision in "${from_revision}" "${to_revision}"; do
  if [[ ! "${revision}" =~ ^[0-9a-fA-F]{40,64}$ ]]; then
    echo "离线安装源码版本元数据非法" >&2
    exit 2
  fi
done
for source_state in "${from_source_state}" "${to_source_state}"; do
  if [[ "${source_state}" != "clean" && "${source_state}" != "dirty" ]]; then
    echo "离线安装源码状态元数据非法" >&2
    exit 2
  fi
done

started_at_utc="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
umask 077
mkdir -p "$(dirname "${evidence_file}")"

write_evidence() {
  local status="$1"
  local failure_stage="$2"
  local rollback_status="$3"
  (
    set -o noclobber
    printf '{"schema_version":1,"status":"%s","failure_stage":"%s","rollback_status":"%s","started_at_utc":"%s","completed_at_utc":"%s","from":{"version":"%s","source_revision":"%s","source_state":"%s"},"to":{"version":"%s","source_revision":"%s","source_state":"%s"}}\n' \
      "${status}" \
      "${failure_stage}" \
      "${rollback_status}" \
      "${started_at_utc}" \
      "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
      "${from_version}" \
      "${from_revision}" \
      "${from_source_state}" \
      "${to_version}" \
      "${to_revision}" \
      "${to_source_state}" >"${evidence_file}"
  )
}

rollback_in_progress=0
backup_ready=0
upgrade_committed=0

perform_rollback() {
  local failure_stage="$1"
  rollback_in_progress=1
  if FLOWTEST_COMPACT_ENV_FILE="${current_compact_directory}/.env" \
    FLOWTEST_COMPACT_IMAGE_ENV_FILE="${current_compact_directory}/images.env" \
    FLOWTEST_RESTORE_CONFIRM=RESTORE \
    "${current_compact_directory}/restore.sh" "${backup_directory}"; then
    backup_ready=0
    if ! write_evidence rolled_back "${failure_stage}" passed; then
      echo "旧版本已恢复，但升级证据写入失败: ${evidence_file}" >&2
      return 1
    fi
    return 0
  fi
  if ! write_evidence rollback_failed "${failure_stage}" failed; then
    echo "升级和自动回滚均失败，且证据写入失败" >&2
  fi
  return 1
}

cleanup() {
  local original_status=$?
  if [[ "${original_status}" -ne 0 && "${backup_ready}" -eq 1 &&
    "${upgrade_committed}" -eq 0 && "${rollback_in_progress}" -eq 0 ]]; then
    echo "升级异常中断，正在尝试自动恢复旧版本" >&2
    set +e
    perform_rollback unexpected_failure
    set -e
  fi
  exit "${original_status}"
}
trap cleanup EXIT

"${compact_directory}/install_offline.sh" --load-only
FLOWTEST_COMPACT_ENV_FILE="${current_compact_directory}/.env" \
FLOWTEST_COMPACT_IMAGE_ENV_FILE="${current_compact_directory}/images.env" \
FLOWTEST_BACKUP_SOURCE_REVISION_FILE="${current_bundle_directory}/SOURCE_REVISION" \
  "${compact_directory}/backup.sh" "${backup_directory}"
backup_ready=1

failure_stage=""
if ! FLOWTEST_COMPACT_ENV_FILE="${current_compact_directory}/.env" \
  FLOWTEST_COMPACT_IMAGE_ENV_FILE="${compact_directory}/images.env" \
  "${compact_directory}/start_offline.sh"; then
  failure_stage=start_or_readiness
elif [[ "${FLOWTEST_S36_FORCE_POST_START_FAILURE:-0}" == "1" ]]; then
  failure_stage=forced_post_start
fi

if [[ -n "${failure_stage}" ]]; then
  echo "新版本未通过升级验收，正在自动恢复旧版本" >&2
  if perform_rollback "${failure_stage}"; then
    echo "旧版本数据、Artifact 和镜像已自动恢复；失败证据: ${evidence_file}" >&2
  else
    echo "自动回滚失败，请停止写入并使用保留备份手工恢复: ${backup_directory}" >&2
  fi
  trap - EXIT
  exit 1
fi

if [[ "${current_compact_directory}" != "${compact_directory}" ]]; then
  if ! (
    set -o noclobber
    umask 077
    cat "${current_compact_directory}/.env" >"${compact_directory}/.env"
  ); then
    echo "新版本目录的 .env 在升级期间发生冲突，正在恢复旧版本" >&2
    exit 1
  fi
  chmod 600 "${compact_directory}/.env"
fi
upgrade_committed=1
backup_ready=0
write_evidence passed none not_required
trap - EXIT

echo "Compact 无外网升级已完成，升级前备份: ${backup_directory}"
echo "新安装目录已激活: ${compact_directory}"
echo "升级证据: ${evidence_file}"
