"""Target URL validation and SSRF-style protections."""
import ipaddress
from urllib.parse import urlparse

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
BLOCKED_HOSTNAMES = {"metadata.google.internal", "metadata", "instance-data"}


class TargetRejected(ValueError):
    """Raised when a URL is not an authorised test target."""


def parse_origin(url):
    if not isinstance(url, str) or not url.strip() or len(url) > 2048:
        raise TargetRejected("Target URL must be a non-empty string of reasonable length.")
    try:
        p = urlparse(url.strip())
        port = p.port
    except ValueError:
        raise TargetRejected("Malformed URL.")
    if p.scheme not in ("http", "https"):
        raise TargetRejected(f"Scheme '{p.scheme}' is not allowed (http/https only).")
    if p.username or p.password:
        raise TargetRejected("URLs containing credentials are not allowed.")
    host = (p.hostname or "").lower()
    if not host:
        raise TargetRejected("URL has no hostname.")
    return p.scheme, host, port, p


def _is_blocked_ip(host):
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    # Cloud metadata (169.254.169.254 / fd00:ec2::254) and link-local ranges are never testable.
    return ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved


def validate_target_url(url, registered_origins):
    """Return the normalised origin if `url` points at a registered, authorised target.

    Rules: scheme http(s); no credentials; host must not be a metadata/link-local address;
    origin (scheme+host+port) must exactly match a registered target; unregistered
    localhost ports are rejected too (prevents probing arbitrary local services)."""
    scheme, host, port, _ = parse_origin(url)
    if host in BLOCKED_HOSTNAMES or _is_blocked_ip(host):
        raise TargetRejected("Cloud-metadata and link-local addresses are blocked.")
    port = port or (443 if scheme == "https" else 80)
    origin = f"{scheme}://{host}:{port}"
    norm = {origin_key(o) for o in registered_origins}
    if origin not in norm:
        raise TargetRejected("Target is not a registered/authorised test target.")
    return origin


def origin_key(url):
    scheme, host, port, _ = parse_origin(url)
    return f"{scheme}://{host}:{port or (443 if scheme == 'https' else 80)}"


def is_request_allowed(request_url, allowed_origin):
    """Used inside the browser: only same-origin requests (plus data:/blob:) may leave the page."""
    if request_url.startswith(("data:", "blob:", "about:")):
        return True
    try:
        return origin_key(request_url) == origin_key(allowed_origin)
    except TargetRejected:
        return False
