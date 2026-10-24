"""An expiry cleanup request carries frozen identity, never new target addresses."""

from app.schemas.self_tests import Digest, SelfTestDTO


class WatchdogRequest(SelfTestDTO):
    manifest_digest: Digest
    binding_fingerprint: Digest
