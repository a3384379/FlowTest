# FlowTest Backend

## 启动

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn app.main:app --reload
```

## 检查

```bash
ruff check .
pytest
```

代码按领域边界组织；`engine` 不依赖 Web 路由，后续可以独立部署为 Worker。
