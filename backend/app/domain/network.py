import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit


class OutboundPolicyError(ValueError):
    """Raised when an outbound URL violates the project network policy."""


AddressResolver = Callable[[str, int], Awaitable[tuple[str, ...]]]


@dataclass(frozen=True, slots=True)
class OutboundNetworkPolicy:
    allowed_hosts: tuple[str, ...] = ()
    allowed_private_cidrs: tuple[str, ...] = ()

    def normalized(self) -> "OutboundNetworkPolicy":
        return OutboundNetworkPolicy(
            allowed_hosts=tuple(sorted({_normalize_host(value) for value in self.allowed_hosts})),
            allowed_private_cidrs=tuple(
                sorted(
                    {
                        str(ipaddress.ip_network(value.strip(), strict=False))
                        for value in self.allowed_private_cidrs
                    }
                )
            ),
        )


async def validate_outbound_url(
    url: str,
    policy: OutboundNetworkPolicy,
    *,
    resolver: AddressResolver | None = None,
) -> tuple[str, ...]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OutboundPolicyError("仅允许具有有效主机名的 HTTP/HTTPS 地址")
    if parsed.username is not None or parsed.password is not None:
        raise OutboundPolicyError("出站地址不能包含用户凭据")

    hostname = parsed.hostname.rstrip(".").lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return await validate_outbound_target(hostname, port, policy, resolver=resolver)


async def validate_outbound_target(
    hostname: str,
    port: int,
    policy: OutboundNetworkPolicy,
    *,
    resolver: AddressResolver | None = None,
) -> tuple[str, ...]:
    if not 1 <= port <= 65535:
        raise OutboundPolicyError("目标端口无效")
    normalized = policy.normalized()
    normalized_hostname = _normalize_host(hostname)
    if normalized_hostname.startswith("*."):
        raise OutboundPolicyError("目标主机不能使用通配符")
    if normalized.allowed_hosts and not any(
        _host_matches(normalized_hostname, pattern) for pattern in normalized.allowed_hosts
    ):
        raise OutboundPolicyError("目标域名不在项目允许列表中")

    addresses = await (resolver or resolve_host)(normalized_hostname, port)
    if not addresses:
        raise OutboundPolicyError("目标域名没有可用地址")
    private_networks = tuple(
        ipaddress.ip_network(value, strict=False) for value in normalized.allowed_private_cidrs
    )
    for value in addresses:
        _validate_address(ipaddress.ip_address(value), private_networks)
    return addresses


async def resolve_host(hostname: str, port: int) -> tuple[str, ...]:
    try:
        records = await asyncio.get_running_loop().getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as error:
        raise OutboundPolicyError("目标域名解析失败") from error
    return tuple(sorted({str(record[4][0]) for record in records}))


def validate_policy_values(allowed_hosts: Iterable[str], private_cidrs: Iterable[str]) -> None:
    for host in allowed_hosts:
        _normalize_host(host)
    for value in private_cidrs:
        network = ipaddress.ip_network(value.strip(), strict=False)
        if not network.is_private:
            raise OutboundPolicyError("私网 CIDR 必须属于私有地址范围")
        if network.overlaps(ipaddress.ip_network("169.254.0.0/16")) or network.overlaps(
            ipaddress.ip_network("fe80::/10")
        ):
            raise OutboundPolicyError("链路本地地址不能加入允许列表")


def _normalize_host(value: str) -> str:
    normalized = value.strip().rstrip(".").lower()
    candidate = normalized[2:] if normalized.startswith("*.") else normalized
    if not candidate or "/" in candidate or "://" in candidate or "*" in candidate:
        raise OutboundPolicyError("允许域名必须是精确域名或 *.example.com 形式")
    try:
        candidate.encode("idna")
    except UnicodeError as error:
        raise OutboundPolicyError("允许域名格式无效") from error
    return normalized


def _host_matches(hostname: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        suffix = pattern[1:]
        return hostname.endswith(suffix) and hostname != suffix[1:]
    return hostname == pattern


def _validate_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    allowed_private_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> None:
    metadata_addresses = {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
    if (
        address in metadata_addresses
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        raise OutboundPolicyError("目标地址属于禁止访问的本地、元数据或保留地址")
    if address.is_private and not any(
        address.version == network.version and address in network
        for network in allowed_private_networks
    ):
        raise OutboundPolicyError("目标地址属于未授权的私有网络")
