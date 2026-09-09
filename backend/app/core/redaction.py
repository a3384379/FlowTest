"""Immutable, request-scoped redaction policy resolution.

Redaction is an output transformation.  It is deliberately separate from
authorization, encryption and the validation of executable workflow values.
The installation default is OFF; a project may explicitly opt in to ON.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import StrEnum

from app.core.config import settings


class RedactionMode(StrEnum):
    OFF = "off"
    ON = "on"


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    mode: RedactionMode
    source: str
    policy_version: int


def installation_redaction_policy() -> RedactionPolicy:
    return RedactionPolicy(
        mode=RedactionMode(settings.redaction_mode),
        source="installation",
        policy_version=settings.redaction_policy_version,
    )


_current_policy: ContextVar[RedactionPolicy | None] = ContextVar(
    "flowtest_redaction_policy",
    default=None,
)


def get_redaction_policy() -> RedactionPolicy:
    return _current_policy.get() or installation_redaction_policy()


def set_redaction_policy(policy: RedactionPolicy) -> Token[RedactionPolicy | None]:
    return _current_policy.set(policy)


def reset_redaction_policy(token: Token[RedactionPolicy | None]) -> None:
    _current_policy.reset(token)


def project_redaction_policy(project: object) -> RedactionPolicy:
    mode = getattr(project, "redaction_mode", None)
    if mode is None:
        return installation_redaction_policy()
    return RedactionPolicy(
        mode=RedactionMode(mode),
        source="project",
        policy_version=int(getattr(project, "redaction_policy_version", 1)),
    )


def persisted_redaction_policy(record: object) -> RedactionPolicy:
    """Resolve the immutable policy captured on a queued execution or AI job."""

    mode = getattr(record, "redaction_mode", None)
    version = getattr(record, "redaction_policy_version", None)
    if mode is None:
        return installation_redaction_policy()
    return RedactionPolicy(
        mode=RedactionMode(str(mode)),
        source="execution",
        policy_version=int(version or 1),
    )


def redaction_enabled() -> bool:
    return get_redaction_policy().mode is RedactionMode.ON
