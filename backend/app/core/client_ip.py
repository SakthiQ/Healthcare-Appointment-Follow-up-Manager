"""Works out the real client IP behind proxies, without trusting what the client can forge.

The login lockout, the per-IP rate limits and the audit log all key on the client IP.
Behind a proxy the TCP peer is the proxy, so the IP has to come from a header, and which
header can be trusted depends on the hosting:

* X-Forwarded-For is a list that each proxy APPENDS to. Its leftmost entries come from the
  client and can be anything; only the entries added by proxies you control are reliable.
  So the client IP is the entry TRUSTED_PROXY_HOPS places from the right: the address the
  outermost trusted proxy saw. (Taking the leftmost entry, as uvicorn does with
  `--forwarded-allow-ips='*'`, lets an attacker pick a fresh IP for every request.)
* Some edge proxies put the client IP in a header of their own and overwrite whatever the
  client sent, e.g. Cloudflare's CF-Connecting-IP. CLIENT_IP_HEADER names such a header;
  it is used first when present.

With neither configured (local development, no proxy) the TCP peer address is used.
Values that are not a valid IP address are ignored.
"""
import ipaddress
from typing import Iterable, Optional, Tuple

from app.config import settings


def _valid_ip(value: str) -> Optional[str]:
    value = value.strip()
    # "[2001:db8::1]:443" / "203.0.113.5:443" style values carry a port; drop it.
    if value.startswith("[") and "]" in value:
        value = value[1:value.index("]")]
    elif value.count(":") == 1:
        value = value.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _header_values(headers: Iterable[Tuple[bytes, bytes]], name: str) -> list:
    wanted = name.lower().encode("latin-1")
    return [v.decode("latin-1") for k, v in headers if k.lower() == wanted]


def resolve_client_ip(scope) -> str:
    """The client IP for an ASGI HTTP scope (see the module docstring)."""
    headers = scope.get("headers") or []

    header_name = (settings.CLIENT_IP_HEADER or "").strip()
    if header_name:
        for value in _header_values(headers, header_name):
            ip = _valid_ip(value.split(",")[0])
            if ip:
                return ip

    hops = settings.TRUSTED_PROXY_HOPS
    if hops > 0:
        entries = [e for v in _header_values(headers, "x-forwarded-for") for e in v.split(",") if e.strip()]
        if len(entries) >= hops:
            ip = _valid_ip(entries[-hops])
            if ip:
                return ip

    client = scope.get("client")
    return client[0] if client else "unknown"
