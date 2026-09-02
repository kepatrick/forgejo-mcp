from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network

from starlette.requests import Request

from forgejo_mcp.config import Settings

_MAX_FORWARDED_HOPS = 32


def get_client_ip(request: Request, settings: Settings) -> str | None:
    """Return the peer IP, trusting X-Forwarded-For only from configured proxies."""
    if request.client is None:
        return None
    peer_text = request.client.host.strip()
    peer = _parse_ip(peer_text)
    if peer is None:
        return peer_text[:255] or None
    if not _is_trusted(peer, settings.trusted_proxy_cidrs):
        return str(peer)

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded is None:
        return str(peer)
    parts = [part.strip() for part in forwarded.split(",")]
    if not parts or len(parts) > _MAX_FORWARDED_HOPS or any(not part for part in parts):
        return str(peer)
    addresses = [_parse_ip(part) for part in parts]
    if any(address is None for address in addresses):
        return str(peer)

    chain = [address for address in addresses if address is not None]
    for address in reversed([*chain, peer]):
        if not _is_trusted(address, settings.trusted_proxy_cidrs):
            return str(address)
    return str(chain[0]) if chain else str(peer)


def _parse_ip(value: str) -> IPv4Address | IPv6Address | None:
    try:
        address = ip_address(value)
    except ValueError:
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _is_trusted(address: IPv4Address | IPv6Address, cidrs: list[str]) -> bool:
    return any(address in ip_network(cidr) for cidr in cidrs)
