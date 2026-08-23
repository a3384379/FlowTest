import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain.api_assets import APIVersionSpec, AuthKind, BodyKind, HttpMethod, JsonValue
from app.domain.test_engineering import OperationContract

SENSITIVE_IMPORT_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "password",
        "proxy-authorization",
        "secret",
        "token",
        "x-api-key",
        "api_key",
        "apikey",
        "access_key",
        "access_token",
        "refresh_token",
        "client_secret",
        "api-key",
    }
)


class ImportSourceType(StrEnum):
    AUTO = "auto"
    OPENAPI3 = "openapi3"
    SWAGGER2 = "swagger2"
    POSTMAN = "postman"
    HAR = "har"
    CURL = "curl"
    BRUNO = "bruno"
    EXCEL = "excel"


class ImportSourceKind(StrEnum):
    FILE = "file"
    URL = "url"


class ImportChange(StrEnum):
    ADDED = "added"
    CHANGED = "changed"
    DELETED = "deleted"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class ImportedOperation:
    name: str
    description: str
    request: APIVersionSpec
    target_base_url: str | None = None
    canonical_contract: OperationContract | None = None

    @property
    def import_key(self) -> str:
        normalized_path = re.sub(r"/+", "/", self.request.path.strip())
        return hashlib.sha256(f"{self.request.method.value}:{normalized_path}".encode()).hexdigest()

    @property
    def content_fingerprint(self) -> str:
        query_parameters: list[JsonValue] = [
            {"name": item.name, "value": item.value, "enabled": item.enabled}
            for item in self.request.query_parameters
        ]
        payload: dict[str, JsonValue] = {
            "name": self.name,
            "description": self.description,
            "method": self.request.method.value,
            "path": self.request.path,
            "query_parameters": query_parameters,
            "headers": _json_string_mapping(self.request.headers),
            "body_kind": self.request.body_kind.value,
            "body": self.request.body,
            "auth_kind": self.request.auth_kind.value,
            "auth_config": _json_string_mapping(self.request.auth_config),
            "target_base_url": self.target_base_url,
            "canonical_contract": (
                self.canonical_contract.model_dump(mode="json", by_alias=True)
                if self.canonical_contract is not None
                else None
            ),
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def _json_string_mapping(values: dict[str, str]) -> dict[str, JsonValue]:
    return {name: value for name, value in values.items()}


def imported_value(name: str, value: str) -> str:
    if not is_sensitive_import_name(name):
        return value
    secret_name = re.sub(r"[^A-Za-z0-9_]", "_", name).upper()
    return f"{{{{secret.IMPORTED_{secret_name}}}}}"


def is_sensitive_import_name(name: str) -> bool:
    lowered = name.lower()
    if lowered in SENSITIVE_IMPORT_NAMES:
        return True
    segments = {segment for segment in re.split(r"[^a-z0-9]+", lowered) if segment}
    if segments & {"authorization", "cookie", "password", "secret", "token"}:
        return True
    normalized = "".join(character for character in lowered if character.isalnum())
    return normalized.endswith(("authorization", "cookie", "password", "secret", "token", "apikey"))


def sanitize_imported_json(value: JsonValue) -> JsonValue:
    if isinstance(value, list):
        return [sanitize_imported_json(item) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                imported_value(key, "")
                if is_sensitive_import_name(key)
                else sanitize_imported_json(item)
            )
            for key, item in value.items()
        }
    return value


def empty_request(*, method: HttpMethod, path: str) -> APIVersionSpec:
    return APIVersionSpec(
        method=method,
        path=path,
        query_parameters=(),
        headers={},
        body_kind=BodyKind.NONE,
        body=None,
        auth_kind=AuthKind.NONE,
        auth_config={},
    )
