from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ServiceContractVersion:
    id: UUID
    kind: Literal["openapi", "pact"]
    version: str | None
    source_name: str
    service_role: Literal["provider", "consumer", "both"]
    status: Literal["completed", "failed"]
    created_at: datetime
