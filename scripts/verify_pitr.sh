#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

database_name="${POSTGRES_DB:-flowtest}"
database_user="${POSTGRES_USER:-flowtest}"
drill_id="$(date -u +%Y%m%d%H%M%S)-$$"
container_name="flowtest-pitr-drill-${drill_id}"
volume_name="flowtest_pitr_drill_${drill_id}"

cleanup() {
  exit_code=$?
  trap - EXIT
  docker rm --force "$container_name" >/dev/null 2>&1 || true
  if [[ "$volume_name" == flowtest_pitr_drill_* ]]; then
    docker volume rm "$volume_name" >/dev/null 2>&1 || true
  fi
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 \
    -c 'DROP TABLE IF EXISTS flowtest_pitr_probe' >/dev/null 2>&1 || true
  exit "$exit_code"
}
trap cleanup EXIT

postgres_container="$(docker compose ps --quiet postgres)"
postgres_image="$(docker compose images --quiet postgres)"
if [[ -z "$postgres_container" || -z "$postgres_image" ]]; then
  echo "PostgreSQL 服务未运行或镜像不存在。" >&2
  exit 1
fi

archive_mode="$(docker compose exec -T postgres psql -Atc 'SHOW archive_mode')"
if [[ "$archive_mode" != "on" ]]; then
  echo "PITR 未启用。请先运行 FLOWTEST_PITR_ENABLED=true docker compose up -d --build postgres。" >&2
  exit 1
fi

network_name="$(
  docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{"\n"}}{{end}}' \
    "$postgres_container" | head -n 1
)"
if [[ -z "$network_name" ]]; then
  echo "无法解析 PostgreSQL 所在 Docker 网络。" >&2
  exit 1
fi

docker compose exec -T postgres psql -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS flowtest_pitr_probe (
  marker text PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
TRUNCATE flowtest_pitr_probe;
INSERT INTO flowtest_pitr_probe (marker) VALUES ('base');
CHECKPOINT;
SQL

docker compose exec -T postgres wal-g backup-push /var/lib/postgresql/data
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 \
  -c "INSERT INTO flowtest_pitr_probe (marker) VALUES ('before-target')"
docker compose exec -T postgres psql -Atc 'SELECT pg_switch_wal()' >/dev/null
target_time="$(docker compose exec -T postgres psql -Atc 'SELECT clock_timestamp()')"
sleep 1
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 \
  -c "INSERT INTO flowtest_pitr_probe (marker) VALUES ('after-target')"
docker compose exec -T postgres psql -Atc 'SELECT pg_switch_wal()' >/dev/null

docker volume create "$volume_name" >/dev/null
walg_s3_prefix="${WALG_S3_PREFIX:-s3://flowtest-artifacts/pitr/postgres}"
walg_endpoint="${WALG_AWS_ENDPOINT:-http://minio:9000}"
walg_key="${FLOWTEST_PITR_ENCRYPTION_KEY:-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef}"

common_environment=(
  --env "WALG_S3_PREFIX=$walg_s3_prefix"
  --env "AWS_ENDPOINT=$walg_endpoint"
  --env "AWS_ACCESS_KEY_ID=${MINIO_ROOT_USER:-flowtest}"
  --env "AWS_SECRET_ACCESS_KEY=${MINIO_ROOT_PASSWORD:-flowtest-local-secret}"
  --env "AWS_REGION=${WALG_AWS_REGION:-us-east-1}"
  --env AWS_S3_FORCE_PATH_STYLE=true
  --env WALG_COMPRESSION_METHOD=zstd
  --env "WALG_LIBSODIUM_KEY=$walg_key"
  --env WALG_LIBSODIUM_KEY_TRANSFORM=hex
)

docker run --rm \
  --network "$network_name" \
  --volume "$volume_name:/restore" \
  "${common_environment[@]}" \
  --entrypoint /bin/bash \
  "$postgres_image" \
  -euc 'wal-g backup-fetch /restore LATEST; chown -R postgres:postgres /restore; touch /restore/recovery.signal; chown postgres:postgres /restore/recovery.signal'

docker run --detach \
  --name "$container_name" \
  --network "$network_name" \
  --volume "$volume_name:/var/lib/postgresql/data" \
  "${common_environment[@]}" \
  --env "POSTGRES_DB=$database_name" \
  --env "POSTGRES_USER=$database_user" \
  --env "POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-flowtest}" \
  "$postgres_image" \
  postgres \
  -c "restore_command=wal-g wal-fetch %f %p" \
  -c "recovery_target_time=$target_time" \
  -c recovery_target_action=promote >/dev/null

for _ in $(seq 1 90); do
  if docker exec "$container_name" pg_isready -U "$database_user" -d "$database_name" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! docker exec "$container_name" pg_isready -U "$database_user" -d "$database_name" >/dev/null 2>&1; then
  docker logs "$container_name" >&2
  echo "PITR 恢复实例未在 90 秒内就绪。" >&2
  exit 1
fi

markers="$(
  docker exec "$container_name" psql -U "$database_user" -d "$database_name" -Atc \
    'SELECT marker FROM flowtest_pitr_probe ORDER BY marker'
)"
expected_markers=$'base\nbefore-target'
if [[ "$markers" != "$expected_markers" ]]; then
  echo "PITR 数据断言失败。期望恢复到目标时间之前，实际 marker：" >&2
  echo "$markers" >&2
  exit 1
fi

echo "PITR 隔离恢复验证通过：目标时间 ${target_time}，仅恢复目标时间之前的数据。"
