#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="${1:-${compact_directory}/.env}"

if [[ -e "${target}" || -L "${target}" ]]; then
  echo "拒绝覆盖已有配置: ${target}" >&2
  exit 2
fi
if ! command -v openssl >/dev/null 2>&1; then
  echo "生成安全密钥需要 openssl" >&2
  exit 2
fi

umask 077
secret_key="$(openssl rand -hex 32)"
admin_password="$(openssl rand -hex 16)"
data_encryption_key="$(openssl rand -base64 32 | tr -d '\n')"
postgres_password="$(openssl rand -hex 24)"
minio_password="$(openssl rand -hex 24)"

cat >"${target}" <<EOF
COMPOSE_PROJECT_NAME=flowtest-compact
FLOWTEST_ENVIRONMENT=compact
FLOWTEST_BIND_ADDRESS=127.0.0.1
FLOWTEST_HTTP_PORT=3000
FLOWTEST_S3_PORT=9000
FLOWTEST_PUBLIC_ORIGIN=http://localhost:3000
FLOWTEST_SECURE_COOKIES=false
FLOWTEST_BOOTSTRAP_ADMIN_EMAIL=admin@flowtest.dev
FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD=${admin_password}
FLOWTEST_SECRET_KEY=${secret_key}
FLOWTEST_DATA_ENCRYPTION_KEY=${data_encryption_key}
FLOWTEST_DATA_ENCRYPTION_KEYRING={}
FLOWTEST_WORKER_CONCURRENCY=2
POSTGRES_PASSWORD=${postgres_password}
MINIO_ROOT_USER=flowtest
MINIO_ROOT_PASSWORD=${minio_password}
EOF

echo "已生成权限为 0600 的配置: ${target}"
