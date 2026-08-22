from dataclasses import dataclass
from typing import Protocol

from app.domain.network import OutboundNetworkPolicy


@dataclass(frozen=True, slots=True)
class ImportDocumentOption:
    id: str
    name: str
    url: str
    display_url: str


@dataclass(frozen=True, slots=True)
class ImportUrlDiscovery:
    source_url: str
    source_kind: str
    documents: tuple[ImportDocumentOption, ...]


@dataclass(frozen=True, slots=True)
class FetchedImportDocument:
    content: bytes
    source_page_url: str
    resolved_url: str
    source_name: str
    document_id: str
    discovered_from_page: bool


class ImportDocumentFetcher(Protocol):
    async def discover(
        self,
        *,
        url: str,
        network_policy: OutboundNetworkPolicy,
        maximum_bytes: int,
    ) -> ImportUrlDiscovery: ...

    async def fetch(
        self,
        *,
        url: str,
        network_policy: OutboundNetworkPolicy,
        maximum_bytes: int,
        document_id: str | None = None,
    ) -> FetchedImportDocument: ...
