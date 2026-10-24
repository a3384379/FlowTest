"""Known read-only errors may be resolved only under a pre-authorized field policy."""

from __future__ import annotations

from scripts.selftest.contracts import Contract, Sha256, canonical_digest
from scripts.selftest.host_contracts import HostToolReceipt
from scripts.selftest.host_gateway import BoundedGateway, ToolExchange
from scripts.selftest.io import HarnessError, JsonObject, text_value, write_json


class RepairProof(Contract):
    failed_sequence: int
    resolved_sequence: int
    tool_name: str
    error_code: str
    changed_fields: tuple[str, ...]
    unchanged_fields_digest: Sha256
    policy_digest: Sha256


def _arguments(exchange: ToolExchange) -> JsonObject:
    value = exchange.arguments.get("request")
    return value if isinstance(value, dict) else exchange.arguments


def resolve_known_read_errors(gateway: BoundedGateway) -> tuple[RepairProof, ...]:
    policies = {item.tool_name: item for item in gateway.authorization.read_only_repairs}
    exchanges = {item.sequence: item for item in gateway.exchanges}
    proofs = []
    for index, receipt in enumerate(gateway.receipts):
        if receipt.outcome == "completed" and receipt.business_success:
            continue
        policy = policies.get(receipt.tool_name)
        failed = exchanges.get(receipt.sequence)
        if (
            receipt.outcome != "completed"
            or not policy
            or not failed
            or receipt.error_code not in policy.error_codes
        ):
            raise HarnessError("HOST_UNRESOLVED_OR_UNKNOWN_TOOL_FAILURE")
        candidates = [
            item
            for item in gateway.receipts
            if item.sequence > receipt.sequence
            and item.tool_name == receipt.tool_name
            and item.outcome == "completed"
            and item.business_success
        ]
        proof = _resolution(
            failed,
            candidates,
            exchanges,
            policy.model_dump(mode="json"),
            policy.allowed_argument_fields,
            text_value(receipt.error_code),
        )
        proofs.append(proof)
        updated = receipt.model_copy(update={"resolved_by": proof.resolved_sequence})
        gateway.receipts[index] = updated
        write_json(gateway.directory / "tool-receipts" / f"{receipt.sequence:03}.json", updated)
    return tuple(proofs)


def _resolution(
    failed: ToolExchange,
    candidates: list[HostToolReceipt],
    exchanges: dict[int, ToolExchange],
    policy: JsonObject,
    allowed: tuple[str, ...],
    error_code: str,
) -> RepairProof:
    original = _arguments(failed)
    for receipt in candidates:
        resolved = exchanges.get(receipt.sequence)
        if resolved is None:
            continue
        revised = _arguments(resolved)
        changed = tuple(
            sorted(
                key
                for key in original.keys() | revised.keys()
                if canonical_digest(original.get(key)) != canonical_digest(revised.get(key))
            )
        )
        immutable = {key: value for key, value in original.items() if key not in allowed}
        if (
            changed
            and set(changed) <= set(allowed)
            and immutable == {key: value for key, value in revised.items() if key not in allowed}
        ):
            return RepairProof(
                failed_sequence=failed.sequence,
                resolved_sequence=resolved.sequence,
                tool_name=failed.name,
                error_code=error_code,
                changed_fields=changed,
                unchanged_fields_digest=canonical_digest(immutable),
                policy_digest=canonical_digest(policy),
            )
    raise HarnessError("HOST_READ_ERROR_RESOLUTION_NOT_PROVEN")
