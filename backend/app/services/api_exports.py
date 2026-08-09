import json
import shlex
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from typing import cast
from urllib.parse import urlencode
from uuid import UUID

from openpyxl import Workbook
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import redact
from app.models.access import User
from app.models.api_assets import APIDefinition, APIVersion
from app.repositories.api_assets import APIAssetRepository
from app.services.projects import ProjectService


class APIExportFormat(StrEnum):
    HAR = "har"
    CURL = "curl"
    BRUNO = "bruno"
    EXCEL = "excel"


@dataclass(frozen=True, slots=True)
class APIExportDocument:
    filename: str
    media_type: str
    content: bytes


@dataclass(frozen=True, slots=True)
class ExportedAPI:
    definition: APIDefinition
    version: APIVersion


class APIExportService:
    def __init__(self, session: AsyncSession) -> None:
        self._assets = APIAssetRepository(session)
        self._projects = ProjectService(session)

    async def export(
        self, *, actor: User, project_id: UUID, export_format: APIExportFormat
    ) -> APIExportDocument:
        access = await self._projects.get(actor=actor, project_id=project_id)
        definitions, _ = await self._assets.list_definitions(
            project_id=project_id,
            offset=0,
            limit=10_000,
        )
        items = await self._load_versions(definitions)
        safe_name = (
            "".join(
                character if character.isalnum() or character in {"-", "_"} else "-"
                for character in access.project.name
            ).strip("-")
            or "flowtest"
        )
        if export_format is APIExportFormat.HAR:
            return APIExportDocument(
                f"{safe_name}.har",
                "application/json",
                _json_bytes(_har_document(items)),
            )
        if export_format is APIExportFormat.CURL:
            commands = "\n\n".join(_curl_command(item) for item in items)
            return APIExportDocument(f"{safe_name}.curl.txt", "text/plain", commands.encode())
        if export_format is APIExportFormat.BRUNO:
            return APIExportDocument(
                f"{safe_name}.bruno.json",
                "application/json",
                _json_bytes(_bruno_document(access.project.name, items)),
            )
        return APIExportDocument(
            f"{safe_name}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            _excel_document(items),
        )

    async def _load_versions(self, definitions: list[APIDefinition]) -> list[ExportedAPI]:
        items: list[ExportedAPI] = []
        for definition in definitions:
            version = await self._assets.get_version(
                definition_id=definition.id,
                version=definition.current_version,
            )
            if version is not None:
                items.append(ExportedAPI(definition, version))
        return items


def _har_document(items: list[ExportedAPI]) -> dict[str, JsonValue]:
    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "FlowTest", "version": "2"},
            "entries": [
                {
                    "comment": item.definition.name,
                    "request": {
                        "method": item.version.method,
                        "url": f"http://flowtest.local{_request_target(item.version)}",
                        "httpVersion": "HTTP/1.1",
                        "headers": [
                            {"name": name, "value": value}
                            for name, value in _safe_headers(item.version.headers).items()
                        ],
                        "queryString": [
                            {"name": name, "value": value}
                            for name, value in _safe_query_items(item.version)
                        ],
                        "postData": _har_post_data(item.version),
                    },
                    "response": {
                        "status": 0,
                        "statusText": "",
                        "httpVersion": "HTTP/1.1",
                        "headers": [],
                        "content": {"size": 0, "mimeType": "application/json"},
                        "redirectURL": "",
                        "headersSize": -1,
                        "bodySize": -1,
                    },
                    "startedDateTime": item.version.created_at.isoformat(),
                    "time": 0,
                }
                for item in items
            ],
        }
    }


def _curl_command(item: ExportedAPI) -> str:
    parts = ["curl", "-X", item.version.method, shlex.quote(_request_target(item.version))]
    for name, value in _safe_headers(item.version.headers).items():
        parts.extend(["-H", shlex.quote(f"{name}: {value}")])
    if item.version.body is not None:
        parts.extend(
            ["--data-raw", shlex.quote(json.dumps(_safe_body(item.version), ensure_ascii=False))]
        )
    return " ".join(parts)


def _bruno_document(project_name: str, items: list[ExportedAPI]) -> dict[str, JsonValue]:
    return {
        "bruno": "FlowTest Collection",
        "version": "1",
        "name": project_name,
        "items": [
            {
                "name": item.definition.name,
                "description": item.definition.description,
                "request": {
                    "method": item.version.method,
                    "url": _request_target(item.version),
                    "headers": cast(JsonValue, _safe_headers(item.version.headers)),
                    "body": _safe_body(item.version),
                },
            }
            for item in items
        ],
    }


def _excel_document(items: list[ExportedAPI]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    if sheet is None:
        raise RuntimeError("Excel workbook has no active sheet")
    sheet.title = "APIs"
    sheet.append(
        [
            "name",
            "method",
            "path",
            "description",
            "query",
            "headers",
            "body",
            "auth_kind",
            "auth_config",
        ]
    )
    for item in items:
        query = dict(_safe_query_items(item.version))
        sheet.append(
            [
                _excel_safe_cell(item.definition.name),
                _excel_safe_cell(item.version.method),
                _excel_safe_cell(item.version.path),
                _excel_safe_cell(item.definition.description),
                _excel_safe_cell(json.dumps(query, ensure_ascii=False)),
                _excel_safe_cell(
                    json.dumps(_safe_headers(item.version.headers), ensure_ascii=False)
                ),
                _excel_safe_cell(json.dumps(_safe_body(item.version), ensure_ascii=False))
                if item.version.body is not None
                else "",
                _excel_safe_cell(item.version.auth_kind),
                _excel_safe_cell(
                    json.dumps(_safe_auth(item.version.auth_config), ensure_ascii=False)
                ),
            ]
        )
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _request_target(version: APIVersion) -> str:
    query = _safe_query_items(version)
    return f"{version.path}?{urlencode(query)}" if query else version.path


def _har_post_data(version: APIVersion) -> JsonValue:
    if version.body is None:
        return None
    return {
        "mimeType": "application/json",
        "text": json.dumps(_safe_body(version), ensure_ascii=False),
    }


def _safe_query_items(version: APIVersion) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for parameter in version.query_parameters:
        if not parameter.get("enabled", True):
            continue
        name = str(parameter["name"])
        safe = cast(dict[str, str], redact({name: str(parameter.get("value", ""))}))
        result.append((name, safe[name]))
    return result


def _safe_body(version: APIVersion) -> JsonValue:
    return cast(JsonValue, redact(version.body))


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    return cast(dict[str, str], redact(headers))


def _safe_auth(auth: dict[str, str]) -> dict[str, str]:
    return cast(dict[str, str], redact(auth))


def _excel_safe_cell(value: str) -> str:
    return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value


def _json_bytes(value: dict[str, JsonValue]) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode()
