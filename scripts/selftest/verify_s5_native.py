"""Independent file bytes and branch-cookie checks; never import production oracles."""

import base64
import binascii
import hashlib

from scripts.selftest.contracts import (
    ExpectedOutcome,
    Finding,
    ScenarioObservation,
)


def _finding(code: str, *, incomplete: bool = False) -> Finding:
    return Finding(
        code=code,
        status="incomplete" if incomplete else "mismatched",
        message="合成文件或并行 Cookie 独立证据缺失或不符合冻结预期",
    )


def verify_s5_native(
    expected: ExpectedOutcome, observed: ScenarioObservation
) -> tuple[Finding, ...]:
    findings = list(_file_findings(expected, observed))
    findings.extend(_created_file_findings(expected, observed))
    if expected.isolated_cookies:
        findings.extend(_cookie_findings(observed))
    return tuple(findings)


def _created_file_findings(
    expected: ExpectedOutcome, observed: ScenarioObservation
) -> tuple[Finding, ...]:
    wanted, actual = expected.created_file, observed.created_file
    if wanted is None:
        return ()
    if actual is None or observed.execution is None:
        return (_finding("S5_PRODUCT_FILE_EVIDENCE_MISSING", incomplete=True),)
    try:
        content = base64.b64decode(actual.content_base64, validate=True)
    except (binascii.Error, ValueError):
        return (_finding("S5_PRODUCT_FILE_ENCODING_CHANGED"),)
    started = observed.execution.started_at
    if wanted.timestamp_precision == "second":
        started = started.replace(microsecond=0)
    if (
        actual.artifact_id != actual.native_uploaded_id
        or sorted(actual.observed_artifact_ids)
        != sorted((*wanted.previous_artifact_ids, actual.artifact_id))
        or actual.artifact_id in wanted.previous_artifact_ids
        or actual.project_id != wanted.project_id
        or actual.created_by_id != wanted.created_by_id
        or actual.content_type != wanted.content_type
        or (actual.filename, actual.size_bytes, actual.sha256)
        != (wanted.filename, wanted.size_bytes, wanted.sha256)
        or content != wanted.content_utf8.encode("utf-8")
        or len(content) != wanted.size_bytes
        or hashlib.sha256(content).hexdigest() != wanted.sha256
        or actual.requested_download_origin != wanted.target_origin
        or actual.requested_download_path
        != f"/api/v1/projects/{wanted.project_id}/files/{actual.artifact_id}"
    ):
        return (_finding("S5_PRODUCT_FILE_CONTENT_OR_SOURCE_CHANGED"),)
    if (
        actual.created_at.tzinfo is None
        or actual.observed_at.tzinfo is None
        or observed.execution.completed_at is None
        or not started <= actual.created_at <= observed.execution.completed_at <= actual.observed_at
    ):
        return (_finding("S5_PRODUCT_FILE_NOT_CREATED_BY_THIS_RUN"),)
    return ()


def _file_findings(expected: ExpectedOutcome, observed: ScenarioObservation) -> tuple[Finding, ...]:
    golden, actual = expected.synthetic_artifact, observed.synthetic_artifact
    if golden is None:
        return ()
    if actual is None:
        return (_finding("S5_FILE_DOWNLOAD_MISSING", incomplete=True),)
    try:
        content = base64.b64decode(actual.content_base64, validate=True)
    except (binascii.Error, ValueError):
        return (_finding("S5_FILE_ENCODING_CHANGED"),)
    if (
        (actual.artifact_id, actual.project_id, actual.content_type)
        != (golden.artifact_id, golden.project_id, golden.content_type)
        or content != golden.content_utf8.encode("utf-8")
        or len(content) != golden.size_bytes
        or hashlib.sha256(content).hexdigest() != golden.sha256
    ):
        return (_finding("S5_FILE_CONTENT_OR_OWNERSHIP_CHANGED"),)
    uploads = (
        [
            entry.binary_request
            for entry in observed.journal.entries
            if entry.binary_request is not None
        ]
        if observed.journal is not None
        else []
    )
    if len(uploads) != int(expected.uploaded_synthetic_file):
        return (_finding("S5_FILE_UPLOAD_RECEIPT_MISSING", incomplete=True),)
    if uploads and (
        (uploads[0].sha256, uploads[0].size_bytes, uploads[0].content_type)
        != (golden.sha256, golden.size_bytes, golden.content_type)
    ):
        return (_finding("S5_FILE_UPLOAD_CHANGED"),)
    return ()


def _cookie_findings(observed: ScenarioObservation) -> tuple[Finding, ...]:
    journal = observed.journal
    if journal is None or len(journal.entries) != 6:
        return (_finding("S5_COOKIE_RECEIPTS_MISSING", incomplete=True),)
    barriers: list[float] = []
    checks: list[float] = []
    for branch in ("left", "right"):
        entries = [e for e in journal.entries if e.request_body and e.request_body.branch == branch]
        snapshots = [entry.synthetic_cookie for entry in entries]
        if any(snapshot is None for snapshot in snapshots):
            return (_finding("S5_COOKIE_RECEIPTS_MISSING", incomplete=True),)
        if [(s.stage, s.value) for s in snapshots if s is not None] != [
            ("set", None),
            ("barrier", branch),
            ("check", branch),
        ]:
            return (_finding("S5_COOKIE_BRANCH_LEAK"),)
        timing = [entry.received_at for entry in entries if entry.received_at is not None]
        if len(entries) != 3 or len(timing) != 3:
            return (_finding("S5_COOKIE_TIMING_MISSING", incomplete=True),)
        barriers.append(timing[1])
        checks.append(timing[2])
    if max(barriers) > min(checks):
        return (_finding("S5_COOKIE_BARRIER_NOT_OBSERVED"),)
    return ()
