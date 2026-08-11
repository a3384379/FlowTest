#!/bin/sh
set -eu

if [ "${FLOWTEST_PITR_ENABLED:-false}" = "true" ]; then
  exec docker-entrypoint.sh "$@" \
    -c archive_mode=on \
    -c wal_level=replica \
    -c archive_timeout=60s \
    -c "archive_command=wal-g wal-push %p"
fi

exec docker-entrypoint.sh "$@"
