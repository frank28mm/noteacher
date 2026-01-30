from __future__ import annotations

import io
import logging
from typing import List, Optional

from homework_agent.utils.url_image_helpers import (
    _normalize_public_url,
    _safe_fetch_public_url_bytes,
)
from homework_agent.utils.settings import get_settings

logger = logging.getLogger(__name__)


def _create_proxy_image_urls(
    urls: List[str],
    *,
    session_id: str,
    prefix: str = "proxy/",
    max_side: int = 1600,
    jpeg_quality: int = 85,
) -> Optional[List[str]]:
    """
    Best-effort: create a smaller, stable public URL copy in Supabase to reduce provider-side fetch failures.
    Only call this when URL fetch is unstable/failing (it downloads + uploads, not cheap).
    """
    cleaned = [str(u).strip() for u in (urls or []) if str(u).strip()]
    if not cleaned:
        return None

    try:
        from PIL import Image
        from homework_agent.utils.supabase_client import get_storage_client
    except Exception as e:
        logger.debug(f"_create_proxy_image_urls import failed: {e}")
        return None

    out: List[str] = []
    storage = get_storage_client()
    base_prefix = f"{prefix.rstrip('/')}/{session_id}/"

    settings = get_settings()
    max_bytes = int(getattr(settings, "max_upload_image_bytes", 5 * 1024 * 1024))

    for u in cleaned:
        try:
            fetched = _safe_fetch_public_url_bytes(
                u,
                timeout_seconds=25.0,
                max_redirects=3,
                max_bytes=max_bytes,
            )
            if not fetched:
                raise RuntimeError("proxy source download failed")

            data, _content_type = fetched
            if not data:
                continue

            img = Image.open(io.BytesIO(data))
            img.load()
            w, h = img.size
            if max(w, h) > int(max_side):
                ratio = float(max_side) / float(max(w, h))
                nw = max(1, int(round(w * ratio)))
                nh = max(1, int(round(h * ratio)))
                img = img.resize((nw, nh), Image.Resampling.LANCZOS)
            if img.mode != "RGB":
                img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=int(jpeg_quality), optimize=True)
            proxy_url = storage.upload_bytes(
                buf.getvalue(),
                mime_type="image/jpeg",
                suffix=".jpg",
                prefix=base_prefix,
            )
            out.append(_normalize_public_url(proxy_url) or proxy_url)
        except Exception as e:
            logger.debug(f"Proxy image creation failed for URL: {e}")
            # Keep a stable list length so downstream can safely index by page.
            out.append(_normalize_public_url(u) or u)

    return out if out else None
