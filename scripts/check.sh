#!/usr/bin/env sh
set -eu

(
  cd backend
  uv run ruff format --check .
  uv run ruff check .
  uv run mypy app
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
