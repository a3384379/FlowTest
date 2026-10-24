# Reuse an explicitly selected, locally built FlowTest runtime and its platform libraries.
ARG FLOWTEST_SELFTEST_RUNTIME_IMAGE
FROM ${FLOWTEST_SELFTEST_RUNTIME_IMAGE} AS candidate
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
RUN rm -rf /app/app /app/migrations
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
RUN uv sync --frozen --no-dev
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM candidate AS fixture
WORKDIR /fixture
COPY mock-target/pyproject.toml mock-target/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN rm -rf /fixture/app
COPY mock-target/app ./app
RUN uv sync --frozen --no-dev
ENV PATH="/fixture/.venv/bin:$PATH"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
