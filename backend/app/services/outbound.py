from app.core.errors import AppError
from app.domain.network import (
    AddressResolver,
    OutboundNetworkPolicy,
    OutboundPolicyError,
    validate_outbound_url,
)


class OutboundRequestGuard:
    def __init__(self, resolver: AddressResolver | None = None) -> None:
        self._resolver = resolver

    async def enforce(self, url: str, policy: OutboundNetworkPolicy) -> tuple[str, ...]:
        try:
            return await validate_outbound_url(url, policy, resolver=self._resolver)
        except OutboundPolicyError as error:
            raise AppError(
                code="OUTBOUND_REQUEST_BLOCKED",
                message=str(error),
                status_code=422,
            ) from error


outbound_request_guard = OutboundRequestGuard()
