.PHONY: help install dev-backend dev-frontend test lint format check

help:
	@echo "make install       Install backend and frontend dependencies"
	@echo "make dev-backend   Run FastAPI development server"
	@echo "make dev-frontend  Run Vite development server"
	@echo "make check         Run backend tests/lint and frontend checks"

install:
	python3 -m pip install -e './backend[dev]'
	cd frontend && pnpm install

dev-backend:
	cd backend && uvicorn app.main:app --reload

dev-frontend:
	cd frontend && pnpm dev

test:
	cd backend && pytest

lint:
	cd backend && ruff check .
	cd frontend && pnpm lint

format:
	cd backend && ruff format .

check:
	cd backend && ruff check . && pytest
	cd frontend && pnpm lint && pnpm build
