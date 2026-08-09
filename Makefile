.PHONY: help install dev-backend dev-frontend test test-integration lint format check up down logs

help:
	@echo "make install       Install backend and frontend dependencies"
	@echo "make dev-backend   Run FastAPI development server"
	@echo "make dev-frontend  Run Vite development server"
	@echo "make check         Run backend tests/lint and frontend checks"

install:
	cd backend && uv sync --extra dev
	cd frontend && pnpm install

dev-backend:
	cd backend && uvicorn app.main:app --reload

dev-frontend:
	cd frontend && pnpm dev

test:
	cd backend && uv run pytest

test-integration:
	docker compose up -d postgres redis minio
	cd backend && uv run pytest -m integration

lint:
	cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy app
	cd frontend && pnpm lint

format:
	cd backend && uv run ruff format .
	cd frontend && pnpm format

check:
	cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run pytest
	cd frontend && pnpm format:check && pnpm lint && pnpm test:coverage && pnpm build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200
