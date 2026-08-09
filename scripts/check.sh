#!/usr/bin/env sh
set -eu

(
  cd backend
  uv run ruff format --check . ../scripts/smoke_s3.py ../scripts/smoke_s4.py ../scripts/smoke_s5.py ../scripts/smoke_s6.py ../scripts/smoke_s7.py ../scripts/smoke_s8.py ../scripts/smoke_s9.py ../scripts/smoke_s10.py
  uv run ruff check . ../scripts/smoke_s3.py ../scripts/smoke_s4.py ../scripts/smoke_s5.py ../scripts/smoke_s6.py ../scripts/smoke_s7.py ../scripts/smoke_s8.py ../scripts/smoke_s9.py ../scripts/smoke_s10.py
  uv run mypy app ../scripts/smoke_s3.py ../scripts/smoke_s4.py ../scripts/smoke_s5.py ../scripts/smoke_s6.py ../scripts/smoke_s7.py ../scripts/smoke_s8.py ../scripts/smoke_s9.py ../scripts/smoke_s10.py
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
