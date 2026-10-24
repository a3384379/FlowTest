"""Independent stdlib verification of a frozen synthetic file and target receipt."""

from __future__ import annotations

import hashlib

from scripts.selftest.contracts import ExpectedOutcome, Finding, ScenarioObservation


def verify_binary_file(
    expected: ExpectedOutcome, observed: ScenarioObservation
) -> tuple[Finding, ...]:
    wanted = expected.binary_file
    if wanted is None:
        return ()
    content = wanted.content_utf8.encode("utf-8")
    if len(content) != wanted.size_bytes or hashlib.sha256(content).hexdigest() != wanted.sha256:
        return (
            Finding(
                code="FILE_GOLDEN_INVALID",
                status="error",
                message="固定文件内容、长度和摘要不一致",
            ),
        )
    journal = observed.journal
    if journal is None or len(journal.entries) != 1:
        return (
            Finding(
                code="FILE_RECEIPT_MISSING",
                status="incomplete",
                message="缺少唯一文件目标回执",
            ),
        )
    entry = journal.entries[0]
    binary = entry.binary_response
    if binary is None or entry.response_body is not None:
        return (
            Finding(
                code="FILE_RESPONSE_KIND_MISMATCH",
                status="mismatched",
                message="文件回执与JSON响应类型不符",
            ),
        )
    actual = (binary.size_bytes, binary.sha256, binary.content_type, binary.filename)
    frozen = (wanted.size_bytes, wanted.sha256, wanted.content_type, wanted.filename)
    if (
        actual != frozen
        or entry.method != "GET"
        or not entry.path.endswith("/download")
        or entry.response_status != 200
    ):
        return (
            Finding(
                code="FILE_CONTENT_MISMATCH",
                status="mismatched",
                message="实际文件长度、摘要、类型或下载请求不符",
            ),
        )
    return ()
