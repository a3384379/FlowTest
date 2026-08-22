"""Pure request-target value objects used by every request execution path."""

from dataclasses import dataclass, field
from typing import cast
from uuid import UUID

from pydantic import JsonValue

from app.domain.api_assets import HttpMethod
from app.domain.scopes import ResolvedValue


@dataclass(frozen=True, slots=True)
class ResolvedRequestTarget:
    environment_id: UUID
    environment_key: str
    environment_name: str
    service_id: UUID | None
    service_key: str
    service_name: str
    endpoint_id: UUID | None
    endpoint_variant: str
    endpoint_revision: int
    base_url: str
    path: str
    effective_url: str
    headers: dict[str, ResolvedValue]
    variables: dict[str, ResolvedValue]
    secret_refs: tuple[str, ...]
    connect_timeout_ms: int
    read_timeout_ms: int
    tls_verify: bool
    proxy_ref: str | None
    outbound_policy: dict[str, JsonValue]
    secret_values: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    @property
    def read_timeout_seconds(self) -> float:
        return self.read_timeout_ms / 1000

    def snapshot(self, *, method: HttpMethod, body: JsonValue) -> dict[str, JsonValue]:
        """Return a safe, immutable-at-persistence-boundary target snapshot."""

        return {
            "environment_id": str(self.environment_id),
            "environment_key": self.environment_key,
            "environment_name": self.environment_name,
            "service_id": str(self.service_id) if self.service_id is not None else None,
            "service_key": self.service_key,
            "service_name": self.service_name,
            "endpoint_id": str(self.endpoint_id) if self.endpoint_id is not None else None,
            "endpoint_variant": self.endpoint_variant,
            "endpoint_revision": self.endpoint_revision,
            "resolved_base_url": self.base_url,
            "resolved_path": self.path,
            "resolved_url": self.effective_url,
            "method": method.value,
            "headers": {
                value.name or name: {"value": value.value, "source": value.source.value}
                for name, value in self.headers.items()
            },
            "variables": {
                name: {"value": value.value, "source": value.source.value}
                for name, value in self.variables.items()
            },
            "body": body,
            "secret_refs": list(self.secret_refs),
            "connect_timeout_ms": self.connect_timeout_ms,
            "read_timeout_ms": self.read_timeout_ms,
            "tls_verify": self.tls_verify,
            "proxy_ref": self.proxy_ref,
            "outbound_policy": cast(JsonValue, self.outbound_policy),
        }
