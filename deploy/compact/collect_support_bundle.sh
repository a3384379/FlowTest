#!/usr/bin/env bash
set -euo pipefail

compact_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${compact_directory}/../.." && pwd)"
support_directory="${1:-}"
# shellcheck source=_lib.sh
source "${compact_directory}/_lib.sh"

if [[ -z "${support_directory}" || "${support_directory}" != /* ]]; then
  echo "用法: $0 /绝对路径/新诊断目录" >&2
  exit 2
fi
if [[ -e "${support_directory}" || -L "${support_directory}" ]]; then
  echo "拒绝覆盖已有诊断路径: ${support_directory}" >&2
  exit 2
fi

compact_source_environment
umask 077
mkdir -p "${support_directory}"
chmod 700 "${support_directory}"
cp "${compact_directory}/SUPPORT_BUNDLE_SCOPE.txt" "${support_directory}/SCOPE.txt"
printf 'probe\texit_code\n' >"${support_directory}/PROBE_STATUS.tsv"

record_probe() {
  local probe_name="$1"
  local output_file="$2"
  shift 2
  local exit_code=0
  : >"${support_directory}/${output_file}"
  if "$@" >"${support_directory}/${output_file}" 2>/dev/null; then
    exit_code=0
  else
    exit_code=$?
  fi
  printf '%s\t%s\n' "${probe_name}" "${exit_code}" >>"${support_directory}/PROBE_STATUS.tsv"
}

collect_host() {
  docker info --format \
    $'architecture\t{{.Architecture}}\ncpus\t{{.NCPU}}\nmemory_bytes\t{{.MemTotal}}\nserver_version\t{{.ServerVersion}}'
}

collect_services() {
  local service
  local container_id
  local inspection
  local degraded=0
  printf 'service\tcontainer_id\timage\tstate\thealth\trestart_count\tmemory_limit_bytes\tnano_cpus\n'
  for service in backend frontend minio postgres redis worker; do
    if ! container_id="$(compact_compose ps --all --quiet "${service}" 2>/dev/null)" ||
      [[ -z "${container_id}" ]]; then
      printf '%s\tmissing\tmissing\tmissing\tmissing\t0\t0\t0\n' "${service}"
      degraded=1
      continue
    fi
    if ! inspection="$(docker inspect --format \
      '{{.Id}}\t{{.Config.Image}}\t{{.State.Status}}\t{{if .State.Health}}{{.State.Health.Status}}{{else}}not_configured{{end}}\t{{.RestartCount}}\t{{.HostConfig.Memory}}\t{{.HostConfig.NanoCpus}}' \
      "${container_id}" 2>/dev/null)"; then
      printf '%s\t%s\tunknown\tunknown\tunknown\t0\t0\t0\n' "${service}" "${container_id}"
      degraded=1
      continue
    fi
    printf '%s\t%s\n' "${service}" "${inspection}"
  done
  return "${degraded}"
}

collect_postgres() {
  compact_compose exec -T postgres psql \
    --username flowtest \
    --dbname flowtest \
    --tuples-only \
    --no-align \
    --field-separator $'\t' \
    --command "SELECT 'alembic_revision', version_num FROM alembic_version
      UNION ALL SELECT 'database_size_bytes', pg_database_size(current_database())::text
      UNION ALL SELECT 'active_connections', count(*)::text
        FROM pg_stat_activity WHERE datname = current_database();"
}

collect_redis() {
  local redis_info
  redis_info="$(compact_compose exec -T redis redis-cli --raw INFO memory)"
  printf '%s\n' "${redis_info}" | awk -F: '
    $1 == "used_memory" || $1 == "used_memory_peak" || $1 == "maxmemory" {
      gsub(/\r/, "", $2); print $1 "\t" $2
    }'
}

collect_queues() {
  local queue
  local depth
  printf 'queue\tdepth\n'
  for queue in general celery data ai performance environment; do
    depth="$(compact_compose exec -T redis redis-cli --raw LLEN "${queue}")"
    printf '%s\t%s\n' "${queue}" "${depth//$'\r'/}"
  done
}

collect_storage() {
  compact_compose run --rm --no-deps backend \
    python -m app.operations.storage_transfer summary
}

base_url="http://127.0.0.1:${FLOWTEST_HTTP_PORT:-3000}/api/v1"
record_probe host host.tsv collect_host
record_probe services services.tsv collect_services
record_probe postgres postgres.tsv collect_postgres
record_probe redis redis.tsv collect_redis
record_probe queues queues.tsv collect_queues
record_probe storage storage.json collect_storage
record_probe live live.json curl --fail --silent --show-error --max-time 10 "${base_url}/live"
record_probe ready ready.json curl --fail --silent --show-error --max-time 10 "${base_url}/ready"
record_probe runtime-profile runtime-profile.json \
  curl --fail --silent --show-error --max-time 10 "${base_url}/runtime-profile"

source_revision="unknown"
source_state="unknown"
if command -v git >/dev/null 2>&1 && git -C "${repository_root}" rev-parse HEAD >/dev/null 2>&1; then
  source_revision="$(git -C "${repository_root}" rev-parse HEAD)"
  if [[ -n "$(git -C "${repository_root}" status --porcelain --untracked-files=normal)" ]]; then
    source_state="dirty"
  else
    source_state="clean"
  fi
elif [[ -f "${repository_root}/SOURCE_REVISION" ]]; then
  source_revision="$(tr -d '\r\n' <"${repository_root}/SOURCE_REVISION")"
  if [[ -f "${repository_root}/SOURCE_STATE" ]]; then
    source_state="$(tr -d '\r\n' <"${repository_root}/SOURCE_STATE")"
  fi
fi

compose_version="$(docker compose version --short 2>/dev/null || printf 'unavailable')"
{
  printf 'schema_version\t1\n'
  printf 'generated_at_utc\t%s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  printf 'source_revision\t%s\n' "${source_revision}"
  printf 'source_state\t%s\n' "${source_state}"
  printf 'compose_version\t%s\n' "${compose_version}"
  printf 'raw_logs_included\tfalse\n'
  printf 'container_environment_included\tfalse\n'
  printf 'business_payloads_included\tfalse\n'
} >"${support_directory}/MANIFEST.tsv"

checksum_files=(
  MANIFEST.tsv
  PROBE_STATUS.tsv
  SCOPE.txt
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
: >"${support_directory}/SHA256SUMS"
for filename in "${checksum_files[@]}"; do
  printf '%s  %s\n' \
    "$(compact_sha256 "${support_directory}/${filename}")" \
    "${filename}" >>"${support_directory}/SHA256SUMS"
done

"${compact_directory}/verify_support_bundle.sh" "${support_directory}"
echo "Compact 隐私安全诊断目录已生成: ${support_directory}"
