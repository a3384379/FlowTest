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

- Automatic redaction is OFF by default. Do not expand logging or data collection. Values that
  are not covered by an already-authorized diagnostic capture must stay out of logs; when that
  existing capture is enabled, follow the active installation/project policy: ON applies the
  existing redaction, while OFF does not scan, mask, substitute, or block the authorized values.
  Project policy is request-scoped.
- All externally visible errors use the standard error envelope and include a trace ID.
- Treat target URLs, uploaded files, imported documents, workflow definitions, and templates as untrusted input.
- Secret values are write-only at API boundaries and encrypted at rest.

## Development workflow

- Identify the affected modules and their tests before editing. Make the smallest change that satisfies the task.
- Keep unrelated refactors, historical warnings, and toolchain upgrades outside the task. Report a separate issue if it does not block the current work.
- Run targeted checks while developing. Do not repeat an unchanged failure without a relevant fix or new diagnostic information. Preserve full logs, but read and report the relevant failure summary first.
- Do not treat a targeted pass as proof that the full CI gate or release acceptance passed.

## Validation scope

- Documentation-only changes: check the changed document's format, links, and required structure. CI governance files and executable documentation examples are not automatically documentation-only changes.
- Local backend changes: run relevant Ruff checks and named backend tests with `make test-backend-targeted TARGETS='["tests/test_imports_api.py"]'`. Run `mypy app` when cross-file typing may be affected.
- Local frontend changes: run named Vitest files with `make test-frontend-targeted TARGETS='["src/lib/api.test.ts"]'`, plus affected formatting, lint, type, or build checks as applicable.
- Core or cross-module changes: expand checks to affected integration paths and deployment shapes. Engine, scheduling, authentication, authorization, tenant isolation, execution snapshots, shared contracts, database models or migrations, dependencies, and deployment changes require broader validation before merge.
- During development, do not default to full coverage, Compose, Windows packaging, historical upgrades, or capacity checks. Run them when the change's risk or the merge/release gate requires them.

`make check` remains the complete local backend and frontend check. It runs backend `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy app`, and `uv run pytest`; frontend `pnpm format:check`, `pnpm lint`, `pnpm test:coverage`, and `pnpm build`. Complete end-to-end acceptance uses Playwright against the Compose stack when applicable. Targeted backend tests explicitly disable coverage collection; the full backend 90% and frontend 80% coverage thresholds remain in force.

## Completion and reporting

- Distinguish local targeted validation, remote merge gates for the latest commit, and full release acceptance.
- Report changed files, checks actually run, checks not run, and remaining risks. Never infer a green CI gate or release readiness from a local targeted pass.
- Use `ci:light` only for its allowed documentation scope. Code and development-rule changes require the applicable `ci:milestone` or controlled governance path; do not bypass branch protection or required checks.
