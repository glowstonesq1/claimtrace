"""URL ingestion with SSRF protection. Disabled unless CLAIMTRACE_ALLOW_URL_INGESTION=true.

Defence: resolve once, reject any non-public address, connect to the *validated IP*
(Host header + TLS SNI keep the original name, so certificates still verify), and
repeat the whole check on every redirect hop. This closes DNS-rebinding between
check and fetch (design-review D12/R12).
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from .parsers import IngestError

MAX_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT = 15.0
ALLOWED_PORTS = {80, 443}

Resolver = Callable[[str], list[str]]


def _system_resolve(host: str) -> list[str]:
    return sorted({ai[4][0] for ai in socket.getaddrinfo(host, None)})


def is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not (addr.is_multicast or addr.is_reserved or addr.is_link_local)


def validate_url(url: str, resolve: Resolver = _system_resolve) -> tuple[str, str, int, str]:
    """Return (scheme, host, port, pinned_ip) or raise IngestError."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise IngestError("url_blocked", "Only http and https URLs are allowed.")
    if parts.username or parts.password:
        raise IngestError("url_blocked", "URLs with embedded credentials are not allowed.")
    host = parts.hostname
    if not host:
        raise IngestError("url_blocked", "URL has no host.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise IngestError("url_blocked", "Only ports 80 and 443 are allowed.")
    try:
        ips = [host] if _is_ip_literal(host) else resolve(host)
    except OSError as e:
        raise IngestError("url_unresolvable", "The host name could not be resolved.") from e
    if not ips:
        raise IngestError("url_unresolvable", "The host name could not be resolved.")
    for ip in ips:
        if not is_public_ip(ip):
            raise IngestError("url_blocked", "The URL points to a private, local or reserved network address.")
    return parts.scheme, host, port, ips[0]


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def fetch_url(url: str, resolve: Resolver = _system_resolve, transport: httpx.BaseTransport | None = None) -> tuple[str, bytes]:
    """Fetch a URL safely. Returns (filename_hint, bytes)."""
    current = url
    with httpx.Client(timeout=TIMEOUT, follow_redirects=False, transport=transport) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            scheme, host, port, ip = validate_url(current, resolve)
            parts = urlsplit(current)
            ip_host = f"[{ip}]" if ":" in ip else ip
            pinned = urlunsplit((scheme, f"{ip_host}:{port}", parts.path or "/", parts.query, ""))
            req = client.build_request(
                "GET",
                pinned,
                headers={"Host": host, "Accept": "*/*", "User-Agent": "ClaimTrace/0.1"},
                extensions={"sni_hostname": host} if scheme == "https" else {},
            )
            resp = client.send(req, stream=True)
            try:
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location")
                    if not loc:
                        raise IngestError("url_failed", "Redirect without a location.")
                    current = urljoin(current, loc)
                    continue
                if resp.status_code != 200:
                    raise IngestError("url_failed", f"The server answered with status {resp.status_code}.")
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise IngestError("file_too_large", "The downloaded file is too large.")
            finally:
                resp.close()
            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            name = parts.path.rsplit("/", 1)[-1] or "page"
            ext = {
                "application/pdf": ".pdf",
                "text/markdown": ".md",
                "text/plain": ".txt",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            }.get(ctype)
            if ext is None:
                raise IngestError(
                    "unsupported_file_type", "URL ingestion supports PDF, DOCX, Markdown and plain-text responses only."
                )
            if not name.lower().endswith(ext):
                name += ext
            return name, bytes(body)
    raise IngestError("url_failed", "Too many redirects.")
