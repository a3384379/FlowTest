#!/usr/bin/env sh
set -eu

docker run --rm -v "$PWD:/mnt:ro" -w /mnt \
  koalaman/shellcheck-alpine@sha256:9955be09ea7f0dbf7ae942ac1f2094355bb30d96fffba0ec09f5432207544002 \
  shellcheck scripts/backup.sh scripts/restore.sh scripts/verify_restore.sh

(
  cd backend
  uv run ruff format --check . ../scripts/*.py
  uv run ruff check . ../scripts/*.py
  uv run mypy app ../scripts/*.py
  uv run lint-imports
  uv run pytest
  uv run pip-audit
)
(
  cd frontend
  pnpm format:check
  pnpm lint
  pnpm test:coverage
  pnpm build
  pnpm audit --audit-level high
)
