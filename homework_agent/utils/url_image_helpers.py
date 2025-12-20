from __future__ import annotations

import base64
import logging
import re
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def _is_public_url(url: str) -> bool:
    url = str(url)
    if not url:
        return False
    if re.match(r"^https?://", url) is None:
        return False
    if url.startswith("http://127.") or url.startswith("https://127."):
        return False
    if url.startswith("http://localhost") or url.startswith("https://localhost"):
        return False
    return True


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
        url = getattr(img, "url", None) or (img.get("url") if isinstance(img, dict) else None)
        if url:
            return str(url)
    return None


def _probe_url_head(url: str) -> Optional[str]:
    """Best-effort HEAD probe for debugging (status/content-type/content-length)."""
    if not url:
        return None
    try:
        import httpx

        # Don't inherit local proxy env for public URL probes.
        with httpx.Client(timeout=5.0, follow_redirects=True, trust_env=False) as client:
            r = client.head(url)
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
        import httpx

        # Avoid local proxy interference when downloading public object URLs.
        with httpx.Client(timeout=20.0, follow_redirects=True, trust_env=False) as client:
            r = client.get(url)
        if r.status_code != 200:
            raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)

        content_type = r.headers.get("content-type", "image/jpeg").split(";")[0].strip() or "image/jpeg"
        data = r.content or b""
        if not data:
            return None
        if len(data) > 20 * 1024 * 1024:
            return None
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

