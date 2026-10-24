"""Project-scoped independent download of the artifact created by a native B request."""

import base64
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from scripts.selftest.contracts import CreatedFileEvidence, CreatedFileExpectation
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    object_value,
    objects_value,
    text_value,
)


def _native_http(detail: JsonObject, node_id: str) -> JsonObject:
    nodes = [n for n in objects_value(detail["nodes"]) if n["node_id"] == node_id]
    if len(nodes) != 1 or nodes[0]["status"] != "passed":
        raise HarnessError("S5_PRODUCT_FILE_NATIVE_NODE_MISSING")
    observations = objects_value(object_value(nodes[0]["result"])["observations"])
    if len(observations) != 1:
        raise HarnessError("S5_PRODUCT_FILE_NATIVE_ATTEMPT_CHANGED")
    return observations[0]


def _utc(value: object) -> datetime:
    parsed = datetime.fromisoformat(text_value(value))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


async def observe_created_file(
    detail: JsonObject, reader: PublicAPI, golden: CreatedFileExpectation
) -> CreatedFileEvidence:
    upload = _native_http(detail, "upload_file")
    identity = UUID(text_value(object_value(object_value(upload["response"])["body"])["id"]))
    listing = await reader.object(
        "GET", f"/projects/{golden.project_id}/files?page=1&page_size=100"
    )
    items = objects_value(listing["items"])
    if (
        listing["total"] != len(items)
        or len(items) > 100
        or any(item["project_id"] != str(golden.project_id) for item in items)
    ):
        raise HarnessError("S5_PRODUCT_FILE_LIST_INCOMPLETE")
    matches = [item for item in items if item["id"] == str(identity)]
    if len(matches) != 1:
        raise HarnessError("S5_PRODUCT_FILE_NOT_IN_BOUND_PROJECT")
    metadata = matches[0]
    content, content_type = await reader.download_synthetic_binary(
        f"/projects/{golden.project_id}/files/{identity}"
    )
    download = _native_http(detail, "download_file")
    request = object_value(download["request"])
    url = urlsplit(text_value(request["url"]))
    return CreatedFileEvidence.model_validate(
        {
            "project_id": metadata["project_id"],
            "filename": metadata["filename"],
            "size_bytes": metadata["size_bytes"],
            "sha256": metadata["sha256"],
            "observed_artifact_ids": [item["id"] for item in items],
            "artifact_id": metadata["id"],
            "content_base64": base64.b64encode(content).decode("ascii"),
            "content_type": content_type,
            "native_uploaded_id": str(identity),
            "created_by_id": metadata["created_by_id"],
            "created_at": _utc(metadata["created_at"]),
            "observed_at": datetime.now(UTC),
            "purpose": metadata["purpose"],
            "requested_download_origin": f"{url.scheme}://{url.netloc}",
            "requested_download_path": url.path,
        }
    )
