# FlowTest Backend

## 启动

```bash
uv sync --locked --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
uv run celery -A app.tasking.celery_app.celery_app worker --loglevel=INFO
uv run celery -A app.tasking.celery_app.celery_app beat --loglevel=INFO
```

## 检查

```bash
uv run ruff check .
uv run mypy app
uv run pytest
```

代码按领域边界组织；`engine` 不依赖 Web 路由、Celery 或 ORM。API 只持久化并分发执行 ID，
Worker 使用加密计划调用独立异步协调器。
