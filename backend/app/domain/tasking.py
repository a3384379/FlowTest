import hashlib
import hmac
from datetime import UTC, datetime
from enum import StrEnum


class TestPlanTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    CI = "ci"
    WEBHOOK = "webhook"


class ServiceTokenScope(StrEnum):
    EXECUTE_WORKFLOW = "execute:workflow"
    EXECUTE_TEST_PLAN = "execute:test-plan"


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def webhook_signature(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode() + b"." + body
    return "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def valid_webhook_signature(
    *,
    secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    now: datetime,
    tolerance_seconds: int,
) -> bool:
    try:
        emitted_at = datetime.fromtimestamp(int(timestamp), tz=UTC)
    except (ValueError, OverflowError):
        return False
    if abs((now.astimezone(UTC) - emitted_at).total_seconds()) > tolerance_seconds:
        return False
    return hmac.compare_digest(webhook_signature(secret, timestamp, body), signature)
