from contextvars import ContextVar, Token

_trace_id: ContextVar[str] = ContextVar("trace_id", default="untracked")


def get_trace_id() -> str:
    return _trace_id.get()


def set_trace_id(trace_id: str) -> Token[str]:
    return _trace_id.set(trace_id)


def reset_trace_id(token: Token[str]) -> None:
    _trace_id.reset(token)
