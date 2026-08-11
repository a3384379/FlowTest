#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

archive_mode="$(docker compose exec -T postgres psql -Atc 'SHOW archive_mode')"
if [[ "$archive_mode" != "on" ]]; then
  echo "PITR 未启用。请先运行 FLOWTEST_PITR_ENABLED=true docker compose up -d --build postgres。" >&2
  exit 1
fi

docker compose exec -T postgres wal-g backup-push /var/lib/postgresql/data
docker compose exec -T postgres wal-g backup-list --pretty
