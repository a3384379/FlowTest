#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
support_directory="${1:-}"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

if [[ -z "${support_directory}" || "${support_directory}" != /* ]]; then
  echo "用法: $0 /绝对路径/诊断目录" >&2
  exit 2
fi
if [[ ! -d "${support_directory}" || -L "${support_directory}" ]]; then
  echo "诊断目录不存在或不是普通目录: ${support_directory}" >&2
  exit 2
fi

expected_files=(
  MANIFEST.tsv
  PROBE_STATUS.tsv
  SCOPE.txt
  SHA256SUMS
  host.tsv
  live.json
  postgres.tsv
  queues.tsv
  ready.json
  redis.tsv
  runtime-profile.json
  services.tsv
  storage.json
)

is_expected_file() {
  local candidate="$1"
  local expected
  for expected in "${expected_files[@]}"; do
    if [[ "${candidate}" == "${expected}" ]]; then
      return 0
    fi
  done
  return 1
}

while IFS= read -r -d '' path; do
  filename="$(basename "${path}")"
  if ! is_expected_file "${filename}"; then
    echo "诊断目录包含未登记文件: ${filename}" >&2
    exit 1
  fi
  if [[ ! -f "${path}" || -L "${path}" ]]; then
    echo "诊断目录只允许普通文件: ${filename}" >&2
    exit 1
  fi
done < <(find "${support_directory}" -mindepth 1 -maxdepth 1 -print0)

for filename in "${expected_files[@]}"; do
  if [[ ! -f "${support_directory}/${filename}" || -L "${support_directory}/${filename}" ]]; then
    echo "诊断目录缺少普通文件: ${filename}" >&2
    exit 1
  fi
done

checksum_count=0
checksum_seen=$'\n'
while read -r expected_digest filename; do
  if [[ -z "${expected_digest}" || -z "${filename}" || "${filename}" == "SHA256SUMS" ]]; then
    echo "诊断摘要清单格式无效" >&2
    exit 1
  fi
  if ! is_expected_file "${filename}"; then
    echo "诊断摘要引用未登记文件: ${filename}" >&2
    exit 1
  fi
  if [[ "${checksum_seen}" == *$'\n'"${filename}"$'\n'* ]]; then
    echo "诊断摘要重复引用文件: ${filename}" >&2
    exit 1
  fi
  checksum_seen+="${filename}"$'\n'
  actual_digest="$(compact_sha256 "${support_directory}/${filename}")"
  if [[ "${actual_digest}" != "${expected_digest}" ]]; then
    echo "诊断文件摘要不一致: ${filename}" >&2
    exit 1
  fi
  checksum_count=$((checksum_count + 1))
done <"${support_directory}/SHA256SUMS"

if [[ "${checksum_count}" -ne 12 ]]; then
  echo "诊断摘要应覆盖 12 个数据文件，实际为 ${checksum_count}" >&2
  exit 1
fi

if ! grep -q $'^raw_logs_included\tfalse$' "${support_directory}/MANIFEST.tsv" ||
  ! grep -q $'^container_environment_included\tfalse$' "${support_directory}/MANIFEST.tsv" ||
  ! grep -q $'^business_payloads_included\tfalse$' "${support_directory}/MANIFEST.tsv"; then
  echo "诊断范围声明不完整" >&2
  exit 1
fi

for filename in "${expected_files[@]}"; do
  if [[ "${filename}" == "SHA256SUMS" ]]; then
    continue
  fi
  if LC_ALL=C grep -Eiq \
    'FLOWTEST_(BOOTSTRAP_ADMIN_PASSWORD|DATA_ENCRYPTION_KEY|SECRET_KEY|OIDC_CLIENT_SECRET|AI_API_KEY)|MINIO_ROOT_(USER|PASSWORD)|AUTHORIZATION[[:space:]]*:' \
    "${support_directory}/${filename}"; then
    echo "诊断文件命中禁止收集的凭据字段: ${filename}" >&2
    exit 1
  fi
done

echo "Compact 诊断目录通过文件白名单、隐私边界和 SHA-256 校验"
