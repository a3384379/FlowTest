from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from fastapi import FastAPI
from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import DEPLOYMENT_ENVIRONMENT, SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Span, Status, StatusCode
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.engine.contracts import WorkflowNode
from app.engine.scheduler import ExecutionContext, NodeExecutionError, NodeExecutor

INSTRUMENTATION_NAME = "flowtest"
EXCLUDED_FASTAPI_URLS = "/api/v1/(health|live|ready|metrics)"


def instrument_fastapi(application: FastAPI, engine: AsyncEngine) -> None:
    if not settings.otel_enabled:
        return
    _configure_provider(settings.otel_service_name)
    FastAPIInstrumentor.instrument_app(
        application,
        excluded_urls=EXCLUDED_FASTAPI_URLS,
    )
    HTTPXClientInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


def configure_worker_tracing(service_name: str) -> None:
    if not settings.otel_enabled:
        return
    _configure_provider(service_name)
    HTTPXClientInstrumentor().instrument()


def shutdown_tracing() -> None:
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()


def current_trace_headers() -> dict[str, str]:
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


@contextmanager
def workflow_span(*, execution_id: UUID, project_id: UUID, workflow_version: int) -> Iterator[Span]:
    tracer = trace.get_tracer(INSTRUMENTATION_NAME)
    with tracer.start_as_current_span(
        "flowtest.workflow.run",
        attributes={
            "flowtest.execution.id": str(execution_id),
            "flowtest.project.id": str(project_id),
            "flowtest.workflow.version": workflow_version,
        },
    ) as span:
        yield span


class TracingNodeExecutor:
    def __init__(self, executor: NodeExecutor) -> None:
        self._executor = executor
        self._tracer = trace.get_tracer(INSTRUMENTATION_NAME)

    async def execute(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        execution_error: NodeExecutionError | None = None
        output: JsonValue = None
        with self._tracer.start_as_current_span(
            "flowtest.workflow.node",
            attributes={
                "flowtest.node.id": node.id,
                "flowtest.node.type": node.type.value,
            },
        ) as span:
            try:
                output = await self._executor.execute(node, context)
            except NodeExecutionError as error:
                span.set_attribute("flowtest.error.code", error.code)
                span.set_status(Status(StatusCode.ERROR, error.code))
                execution_error = error
            else:
                span.set_status(Status(StatusCode.OK))
        if execution_error is not None:
            raise execution_error
        return output


def _configure_provider(service_name: str) -> None:
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            DEPLOYMENT_ENVIRONMENT: settings.environment,
            "service.version": settings.app_version,
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(settings.otel_trace_sample_ratio)),
    )
    exporter = OTLPSpanExporter(
        endpoint=_traces_endpoint(settings.otel_exporter_otlp_endpoint),
        headers=settings.otel_exporter_headers,
        timeout=settings.otel_export_timeout_seconds,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def _traces_endpoint(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    return normalized if normalized.endswith("/v1/traces") else f"{normalized}/v1/traces"
