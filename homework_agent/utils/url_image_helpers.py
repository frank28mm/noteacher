from __future__ import annotations

import base64
import ipaddress
import logging
import re
import socket
from typing import TYPE_CHECKING, Any, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from homework_agent.utils.settings import DEFAULT_MAX_UPLOAD_IMAGE_BYTES

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    import httpx


def _is_public_url(url: str) -> bool:
    """Best-effort URL allowlist for user input.

    This function is intentionally conservative on *syntax* (scheme/host) and IP-literals,
    but does not require DNS to be available.

    SSRF-critical paths MUST use `_safe_fetch_public_url*()` which performs DNS resolution
    and validates each hop (including redirects).
    """

    s = str(url or "").strip()
    if not s:
        return False
    try:
        parsed = urlsplit(s)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip().strip(".")
    if not host:
        return False
    host_l = host.lower()
    if host_l in {"localhost"}:
        return False

    # Direct IP literal.
    try:
        ip = ipaddress.ip_address(host_l)
        return bool(ip.is_global)
    except ValueError:
        pass

    # Domain hostname: allow here; SSRF-critical call sites must resolve + validate.
    return True


def _hostname_resolves_to_global_ips(hostname: str) -> bool:
    """Resolve hostname and ensure all resolved A/AAAA are global.

    Used by SSRF-critical fetchers.
    """

    host = (hostname or "").strip().strip(".")
    if not host:
        return False
    host_l = host.lower()
    if host_l in {"localhost"}:
        return False
    try:
        infos = socket.getaddrinfo(host_l, None, proto=socket.IPPROTO_TCP)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        sockaddr = info[4]
        ip_s = sockaddr[0] if isinstance(sockaddr, tuple) and sockaddr else None
        if not ip_s:
            return False
        try:
            ip = ipaddress.ip_address(str(ip_s))
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def _safe_fetch_public_url(
    url: str,
    *,
    method: str = "GET",
    timeout_seconds: float = 20.0,
    max_redirects: int = 3,
) -> "httpx.Response":
    """Fetch a public URL with SSRF guard and safe redirect handling.

    - Denies non-public URLs.
    - Does NOT use httpx automatic redirects; it validates each redirect hop.
    """

    if not _is_public_url(url):
        raise ValueError("URL must be public HTTP/HTTPS")

    try:
        host = urlsplit(str(url)).hostname
    except Exception:
        host = None
    if not host:
        raise ValueError("URL must have hostname")
    # SSRF-critical: require DNS resolution to global IPs.
    try:
        ipaddress.ip_address(host)
        # IP literal is already checked by _is_public_url.
    except ValueError:
        if not _hostname_resolves_to_global_ips(host):
            raise ValueError("Hostname must resolve to public IPs")

    import httpx

    current = str(url)
    with httpx.Client(
        timeout=float(timeout_seconds), follow_redirects=False, trust_env=False
    ) as client:
        for _ in range(int(max_redirects) + 1):
            r = client.request(method, current)
            if r.status_code in {301, 302, 303, 307, 308}:
                loc = (r.headers.get("location") or "").strip()
                if not loc:
                    return r
                next_url = urljoin(str(r.request.url), loc)
                if not _is_public_url(next_url):
                    raise ValueError("Redirect location must be public HTTP/HTTPS")
                try:
                    next_host = urlsplit(str(next_url)).hostname
                except Exception:
                    next_host = None
                if not next_host:
                    raise ValueError("Redirect location must have hostname")
                try:
                    ipaddress.ip_address(str(next_host))
                except ValueError:
                    if not _hostname_resolves_to_global_ips(str(next_host)):
                        raise ValueError("Redirect hostname must resolve to public IPs")
                current = next_url
                continue
            return r

    raise ValueError("Too many redirects")


def _safe_fetch_public_url_bytes(
    url: str,
    *,
    timeout_seconds: float = 20.0,
    max_redirects: int = 3,
    max_bytes: int = DEFAULT_MAX_UPLOAD_IMAGE_BYTES,
) -> Optional[Tuple[bytes, str]]:
    """Fetch bytes for a public URL (SSRF-safe)."""

    try:
        r = _safe_fetch_public_url(
            url,
            method="GET",
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
        )
        if r.status_code != 200:
            return None
        data = r.content or b""
        if not data or len(data) > int(max_bytes):
            return None
        ct = (
            r.headers.get("content-type", "image/jpeg").split(";", 1)[0].strip()
            or "image/jpeg"
        )
        return data, ct
    except Exception as e:
        logger.debug(f"safe fetch failed for {url}: {e}")
        return None


def _normalize_public_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    s = str(url).strip()
    if not s:
        return None
    # Supabase SDK may return URLs with a trailing "?" which can confuse downstream fetchers.
    return s.rstrip("?")


def _strip_base64_prefix(data: str) -> str:
    return re.sub(r"^data:image/[^;]+;base64,", "", data, flags=re.IGNORECASE)


def _first_public_image_url(images: List[Any]) -> Optional[str]:
    for img in images or []:
        url = getattr(img, "url", None) or (
            img.get("url") if isinstance(img, dict) else None
        )
        if url:
            return str(url)
    return None


def _probe_url_head(url: str) -> Optional[str]:
    """Best-effort HEAD probe for debugging (status/content-type/content-length)."""
    if not url:
        return None
    try:
        r = _safe_fetch_public_url(url, method="HEAD", timeout_seconds=5.0)
        ct = r.headers.get("content-type")
        cl = r.headers.get("content-length")
        return f"url_head status={r.status_code} content-type={ct} content-length={cl}"
    except Exception as e:
        return f"url_head probe_failed: {e}"


def _download_as_data_uri(url: str) -> Optional[str]:
    """Best-effort: download image bytes locally and convert to data URI for base64 fallback."""
    if not url:
        return None

    # Try using httpx for public URLs first
    try:
        out = _safe_fetch_public_url_bytes(url, timeout_seconds=20.0, max_redirects=3)
        if not out:
            return None
        data, content_type = out
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{content_type};base64,{b64}"
    except Exception as e:
        logger.debug(f"httpx download failed for {url}: {e}")

    # Try using Supabase SDK for private URLs (e.g., Supabase storage URLs)
    try:
        from homework_agent.utils.supabase_client import get_storage_client

        storage = get_storage_client()

        # Extract bucket and path from Supabase URL
        # URL format: https://xxx.supabase.co/storage/v1/object/public/bucket/path
        if "supabase.co/storage/v1/object/" in url:
            # Parse the URL to get bucket and path
            parts = url.split("/storage/v1/object/public/")[-1]
            if "/" in parts:
                bucket = parts.split("/")[0]
                path = "/".join(parts.split("/")[1:])
            else:
                logger.debug(f"Invalid Supabase URL format: {url}")
                return None

            # Download from Supabase storage
            data = storage.download_bytes(path, bucket_name=bucket)
            if data:
                content_type = "image/jpeg"  # Supabase images are typically JPEG
                b64 = base64.b64encode(data).decode("ascii")
                return f"data:{content_type};base64,{b64}"
    except Exception as e:
        logger.debug(f"Supabase download failed for {url}: {e}")

    logger.debug(f"All download methods failed for URL: {url}")
    return None


def _is_provider_image_fetch_issue(err: Exception) -> bool:
    msg = str(err or "").strip()
    if not msg:
        return False
    return any(
        s in msg
        for s in (
            "Timeout while fetching image_url",
            "timeout while fetching image_url",
            "InvalidParameter",
            "image_url",
            "20040",
        )
    )
