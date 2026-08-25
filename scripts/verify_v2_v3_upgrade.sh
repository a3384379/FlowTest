#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${repo_root}/deploy/upgrade/compose.yaml"
v2_ref="${FLOWTEST_UPGRADE_V2_REF:-v2.0.0-rc.1}"
expected_v2_commit="06699d54bceee091a2efac838e426cf7ef5c9c9e"
current_head_revision="20260823_0045"
actual_v2_commit="$(git -C "${repo_root}" rev-parse "${v2_ref}^{commit}")"

if [[ "${actual_v2_commit}" != "${expected_v2_commit}" ]]; then
  echo "V2 baseline mismatch: expected ${expected_v2_commit}, got ${actual_v2_commit}" >&2
  exit 2
fi

temporary_root="$(mktemp -d "${TMPDIR:-/tmp}/flowtest-v2-v3-upgrade.XXXXXX")"
v2_source="${temporary_root}/v2-source"
backup_root="${temporary_root}/backup"
smoke_output="${temporary_root}/v2-smoke.jsonl"
project_name="flowtest_upgrade_${$}"
api_port="${FLOWTEST_UPGRADE_API_PORT:-}"
if [[ -z "${api_port}" ]]; then
  api_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
fi

export FLOWTEST_UPGRADE_API_PORT="${api_port}"
export FLOWTEST_UPGRADE_V2_BACKEND_IMAGE="flowtest-v2-upgrade:${$}"
export FLOWTEST_UPGRADE_V2_MOCK_IMAGE="flowtest-v2-mock-upgrade:${$}"
export FLOWTEST_UPGRADE_CURRENT_BACKEND_IMAGE="flowtest-current-upgrade:${$}"

compose=(docker compose --project-name "${project_name}" --file "${compose_file}")

cleanup() {
  status=$?
  trap - EXIT INT TERM
  if [[ "${status}" -ne 0 ]]; then
    "${compose[@]}" --profile v2 --profile current logs --no-color || true
  fi
  "${compose[@]}" --profile v2 --profile current down --volumes --remove-orphans || true
  docker image rm \
    "${FLOWTEST_UPGRADE_V2_BACKEND_IMAGE}" \
    "${FLOWTEST_UPGRADE_V2_MOCK_IMAGE}" \
    "${FLOWTEST_UPGRADE_CURRENT_BACKEND_IMAGE}" >/dev/null 2>&1 || true
  rm -rf "${temporary_root}"
  exit "${status}"
}
trap cleanup EXIT INT TERM

assert_revision() {
  expected_revision="$1"
  actual_revision="$(
    "${compose[@]}" exec -T postgres \
      psql --username flowtest --dbname flowtest --tuples-only --no-align \
      --command 'SELECT version_num FROM alembic_version' | tr -d '[:space:]'
  )"
  if [[ "${actual_revision}" != "${expected_revision}" ]]; then
    echo "Migration revision mismatch: expected ${expected_revision}, got ${actual_revision}" >&2
    return 1
  fi
}

storage_transfer() {
  action="$1"
  "${compose[@]}" --profile current run --rm --no-deps \
    --user "$(id -u):$(id -g)" \
    --volume "${repo_root}/scripts/storage_transfer.py:/tmp/storage_transfer.py:ro" \
    --volume "${backup_root}/minio:/backup:rw" \
    current-api python /tmp/storage_transfer.py "${action}" /backup
}

verify_phase() {
  phase="$1"
  if [[ "${phase}" == "v2-rollback" ]]; then
    api_service="v2-api"
  else
    api_service="current-api"
  fi
  "${compose[@]}" --profile current run --rm --no-deps \
    --volume "${repo_root}/scripts:/tmp/scripts:ro" \
    --volume "${temporary_root}:/state:rw" \
    --workdir /tmp/scripts \
    --env "FLOWTEST_SMOKE_API_URL=http://${api_service}:8000/api/v1" \
    current-api python verify_v2_v3_data.py verify \
    --state /state/state.json --phase "${phase}"
  storage_transfer verify
}

mkdir -p "${v2_source}" "${backup_root}/minio"
git -C "${repo_root}" archive "${actual_v2_commit}" | tar -x -C "${v2_source}"

echo "Building isolated V2 and current images..."
docker build --tag "${FLOWTEST_UPGRADE_CURRENT_BACKEND_IMAGE}" "${repo_root}/backend"
docker build --tag "${FLOWTEST_UPGRADE_V2_BACKEND_IMAGE}" "${v2_source}/backend"
docker build --tag "${FLOWTEST_UPGRADE_V2_MOCK_IMAGE}" "${v2_source}/mock-target"

echo "Starting isolated V2 baseline ${v2_ref} (${actual_v2_commit})..."
"${compose[@]}" up --detach --wait postgres redis minio mock-target
"${compose[@]}" --profile v2 run --rm --no-deps v2-api alembic upgrade 20260812_0018
assert_revision 20260812_0018
"${compose[@]}" --profile v2 up --detach --wait v2-api v2-worker

"${compose[@]}" --profile v2 run --rm --no-deps \
  --volume "${v2_source}/scripts:/tmp/scripts:ro" \
  --workdir /tmp/scripts \
  --env "FLOWTEST_SMOKE_API_URL=http://v2-api:8000/api/v1" \
  --env "FLOWTEST_SMOKE_TARGET_URL=http://mock-target:8080" \
  v2-api python smoke_s11.py | tee "${smoke_output}"
"${compose[@]}" --profile current run --rm --no-deps \
  --volume "${repo_root}/scripts:/tmp/scripts:ro" \
  --volume "${temporary_root}:/state:rw" \
  --workdir /tmp/scripts \
  current-api python verify_v2_v3_data.py initialize \
  --smoke-output /state/v2-smoke.jsonl --state /state/state.json

"${compose[@]}" --profile current run --rm --no-deps current-api python -c \
  'import boto3, os; client=boto3.client("s3", endpoint_url=os.environ["FLOWTEST_S3_ENDPOINT_URL"], aws_access_key_id=os.environ["FLOWTEST_S3_ACCESS_KEY"], aws_secret_access_key=os.environ["FLOWTEST_S3_SECRET_KEY"], region_name="us-east-1"); bucket=os.environ["FLOWTEST_S3_BUCKET"]; client.put_object(Bucket=bucket, Key="upgrade-rehearsal/v2-evidence.json", Body=b"{\"source\":\"v2\"}\n", ContentType="application/json")'
"${compose[@]}" exec -T postgres pg_dump \
  --username flowtest --dbname flowtest --format=custom > "${backup_root}/postgres.dump"
test -s "${backup_root}/postgres.dump"
"${compose[@]}" exec -T postgres pg_restore --list < "${backup_root}/postgres.dump" >/dev/null
storage_transfer backup

echo "Upgrading V2 data in place to the current V3 head..."
"${compose[@]}" --profile v2 stop v2-api v2-worker
"${compose[@]}" --profile current run --rm --no-deps current-api alembic upgrade head
"${compose[@]}" --profile current run --rm --no-deps current-api alembic check
assert_revision "${current_head_revision}"
"${compose[@]}" --profile current up --detach --wait current-api current-worker
verify_phase v3-upgrade

echo "Downgrading the same data set to the V2 revision..."
"${compose[@]}" --profile current stop current-api current-worker
"${compose[@]}" --profile current run --rm --no-deps current-api \
  alembic downgrade 20260812_0018
assert_revision 20260812_0018
"${compose[@]}" --profile v2 up --detach --wait v2-api v2-worker
verify_phase v2-rollback

echo "Re-upgrading the rolled-back data set to the current V3 head..."
"${compose[@]}" --profile v2 stop v2-api v2-worker
"${compose[@]}" --profile current run --rm --no-deps current-api alembic upgrade head
"${compose[@]}" --profile current run --rm --no-deps current-api alembic check
assert_revision "${current_head_revision}"
"${compose[@]}" --profile current up --detach --wait current-api current-worker
verify_phase v3-reupgrade

printf '{"status":"passed","baseline":"%s","upgrade":"20260812_0018->%s","rollback":"%s->20260812_0018","reupgrade":"20260812_0018->%s"}\n' \
  "${v2_ref}" "${current_head_revision}" "${current_head_revision}" "${current_head_revision}"
