import ipaddress
from urllib.parse import urlsplit


def normalize_public_http_url(value: object, *, max_length: int = 2048) -> str | None:
    """Return a browser-safe HTTP(S) URL, or None for unsafe/unusable values."""
    if value is None:
        return None
    url = str(value).strip()
    if not url or len(url) > max_length or any(ord(char) < 32 for char in url):
        return None
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if (
        parsed.username
        or parsed.password
        or port is not None
        and not 1 <= port <= 65535
    ):
        return None
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return url
    if not address.is_global:
        return None
    return url
