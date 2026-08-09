# FlowTest Engineering Rules

## Architecture

- HTTP routers adapt requests and responses only. Business rules belong in services or domain modules.
- Domain and execution-engine modules must not import FastAPI, Celery, SQLAlchemy models, or concrete infrastructure clients.
- Infrastructure implementations are injected behind typed interfaces.
- Database changes require an Alembic migration with upgrade and downgrade paths.

## Clean code

- Use English identifiers and explicit types. User-facing text and product documentation are Chinese.
- Keep functions focused and cyclomatic complexity at or below 10.
- Do not use mutable global state, wildcard dictionaries for stable contracts, broad silent exception handlers, or duplicated authorization logic.
- Extract a shared abstraction only after the same stable behavior appears at least three times.
- Add characterization tests before refactoring behavior that is not already covered.
- Keep refactoring commits separate from feature changes when practical.

## Security and observability

- Never log passwords, authorization headers, cookies, tokens, secrets, or unredacted sensitive bodies.
- All externally visible errors use the standard error envelope and include a trace ID.
- Treat target URLs, uploaded files, imported documents, workflow definitions, and templates as untrusted input.
- Secret values are write-only at API boundaries and encrypted at rest.

## Required checks

- Backend: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy app`, and `uv run pytest`.
- Frontend: `pnpm format:check`, `pnpm lint`, `pnpm test:coverage`, and `pnpm build`.
- End-to-end behavior: Playwright against the Compose stack.
