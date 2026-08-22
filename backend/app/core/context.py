from contextvars import ContextVar, Token

from app.domain.tenant import TenantContext

_trace_id: ContextVar[str] = ContextVar("trace_id", default="untracked")
_tenant_context: ContextVar[TenantContext | None] = ContextVar("tenant_context", default=None)


def get_trace_id() -> str:
    return _trace_id.get()


def set_trace_id(trace_id: str) -> Token[str]:
    return _trace_id.set(trace_id)


def reset_trace_id(token: Token[str]) -> None:
    _trace_id.reset(token)


def get_tenant_context() -> TenantContext | None:
    return _tenant_context.get()


def set_tenant_context(context: TenantContext) -> Token[TenantContext | None]:
    return _tenant_context.set(context)


def reset_tenant_context(token: Token[TenantContext | None]) -> None:
    _tenant_context.reset(token)
