"""Minimal read-only source scopes, without inventing target-installation identities."""

from typing import Protocol
from uuid import UUID


class ProjectScope(Protocol):
    @property
    def project_id(self) -> UUID: ...


class FixtureScope(ProjectScope, Protocol):
    @property
    def fixture_environment_id(self) -> UUID: ...

    @property
    def fixture_service_id(self) -> UUID: ...
