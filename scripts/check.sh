#!/usr/bin/env sh
set -eu

(cd backend && ruff check . && pytest)
(cd frontend && pnpm lint && pnpm build)
