#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backup_directory="${1:-}"
if [[ -z "${backup_directory}" || "${backup_directory}" != /* ]]; then
  echo "恢复验证目录必须是绝对路径" >&2
  exit 2
fi
test -f "${backup_directory}/postgres.dump"
test -f "${backup_directory}/minio/manifest.json"

suffix="$$"
network="flowtest_restore_verify_${suffix}"
postgres_volume="flowtest_restore_pg_${suffix}"
minio_volume="flowtest_restore_minio_${suffix}"
postgres_container="flowtest-restore-postgres-${suffix}"
minio_container="flowtest-restore-minio-${suffix}"

cleanup() {
  docker rm -f "${postgres_container}" "${minio_container}" >/dev/null 2>&1 || true
  docker network rm "${network}" >/dev/null 2>&1 || true
  docker volume rm "${postgres_volume}" "${minio_volume}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "${network}" >/dev/null
docker volume create "${postgres_volume}" >/dev/null
docker volume create "${minio_volume}" >/dev/null
docker run -d --name "${postgres_container}" --network "${network}" \
  -e POSTGRES_USER=flowtest -e POSTGRES_PASSWORD=restore-verification \
  -e POSTGRES_DB=flowtest -v "${postgres_volume}:/var/lib/postgresql/data" \
  postgres:17.6-alpine >/dev/null
docker run -d --name "${minio_container}" --network "${network}" \
  -e MINIO_ROOT_USER=flowtest -e MINIO_ROOT_PASSWORD=restore-verification \
  -v "${minio_volume}:/data" \
  minio/minio:RELEASE.2025-07-23T15-54-02Z server /data >/dev/null

for _attempt in $(seq 1 60); do
  if docker exec "${postgres_container}" pg_isready -U flowtest -d flowtest >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "${postgres_container}" pg_isready -U flowtest -d flowtest >/dev/null
for _attempt in $(seq 1 60); do
  if docker exec "${minio_container}" curl -fsS http://localhost:9000/minio/health/live \
    >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "${minio_container}" curl -fsS http://localhost:9000/minio/health/live >/dev/null

docker exec -i "${postgres_container}" pg_restore \
  --username flowtest --dbname flowtest --no-owner --no-acl < "${backup_directory}/postgres.dump"
docker exec "${postgres_container}" psql -U flowtest -d flowtest -v ON_ERROR_STOP=1 \
  -c "SELECT version_num FROM alembic_version" \
  -c "SELECT count(*) AS users FROM users" >/dev/null

docker image inspect flowtest-backend:latest >/dev/null 2>&1 || \
  docker build -t flowtest-backend:latest "${repository_root}/backend" >/dev/null
docker run --rm --network "${network}" \
  -v "${repository_root}/scripts/storage_transfer.py:/tmp/storage_transfer.py:ro" \
  -v "${backup_directory}/minio:/backup:ro" \
  -e FLOWTEST_S3_ENDPOINT_URL="http://${minio_container}:9000" \
  -e FLOWTEST_S3_ACCESS_KEY=flowtest \
  -e FLOWTEST_S3_SECRET_KEY=restore-verification \
  -e FLOWTEST_S3_BUCKET=flowtest-artifacts \
  flowtest-backend:latest python /tmp/storage_transfer.py restore /backup --replace
docker run --rm --network "${network}" \
  -v "${repository_root}/scripts/storage_transfer.py:/tmp/storage_transfer.py:ro" \
  -v "${backup_directory}/minio:/backup:ro" \
  -e FLOWTEST_S3_ENDPOINT_URL="http://${minio_container}:9000" \
  -e FLOWTEST_S3_ACCESS_KEY=flowtest \
  -e FLOWTEST_S3_SECRET_KEY=restore-verification \
  -e FLOWTEST_S3_BUCKET=flowtest-artifacts \
  flowtest-backend:latest python /tmp/storage_transfer.py verify /backup
echo "隔离卷恢复验证通过"
