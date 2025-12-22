from __future__ import annotations

import base64
import io
import logging
from typing import Optional

import httpx
try:
    import numpy as np
    import cv2
    _CV_AVAILABLE = True
except Exception:
    np = None  # type: ignore
    cv2 = None  # type: ignore
    _CV_AVAILABLE = False

from homework_agent.utils.supabase_client import get_storage_client
from homework_agent.utils.settings import get_settings

logger = logging.getLogger(__name__)


def preprocess_image_bytes(data: bytes) -> bytes:
    if not data:
        return data
    if not _CV_AVAILABLE:
        return data
    try:
        buf = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            return data
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        denoise = cv2.fastNlMeansDenoising(gray, h=10)
        thresh = cv2.adaptiveThreshold(
            denoise,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            2,
        )
        ok, encoded = cv2.imencode(".jpg", thresh)
        if not ok:
            return data
        return encoded.tobytes()
    except Exception as e:
        logger.debug(f"preprocess_image_bytes failed: {e}")
        return data


def _bytes_to_data_uri(data: bytes, mime_type: str = "image/jpeg") -> str:
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


def preprocess_image_url(
    url: str,
    *,
    prefix: str,
    timeout_seconds: float = 20.0,
    max_bytes: int = 20 * 1024 * 1024,
) -> Optional[str]:
    if not url:
        return None
    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True, trust_env=False) as client:
            r = client.get(url)
        if r.status_code != 200:
            return None
        data = r.content or b""
        if not data or len(data) > max_bytes:
            return None
        processed = preprocess_image_bytes(data)
        storage = get_storage_client()
        return storage.upload_bytes(
            processed,
            mime_type="image/jpeg",
            suffix=".jpg",
            prefix=prefix,
        )
    except Exception as e:
        logger.debug(f"preprocess_image_url failed: {e}")
        return None


def preprocess_image_url_to_data_uri(
    url: str,
    *,
    timeout_seconds: float = 20.0,
    max_bytes: int = 20 * 1024 * 1024,
) -> Optional[str]:
    if not url:
        return None
    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True, trust_env=False) as client:
            r = client.get(url)
        if r.status_code != 200:
            return None
        data = r.content or b""
        if not data or len(data) > max_bytes:
            return None
        processed = preprocess_image_bytes(data)
        return _bytes_to_data_uri(processed, "image/jpeg")
    except Exception as e:
        logger.debug(f"preprocess_image_url_to_data_uri failed: {e}")
        return None


def maybe_preprocess_for_vision(url: str) -> Optional[str]:
    settings = get_settings()
    if not getattr(settings, "vision_preprocess_enabled", False):
        return None
    return preprocess_image_url_to_data_uri(
        url,
        timeout_seconds=float(getattr(settings, "vision_preprocess_timeout_seconds", 20.0)),
        max_bytes=int(getattr(settings, "vision_preprocess_max_bytes", 20 * 1024 * 1024)),
    )


def maybe_preprocess_for_ocr(url: str) -> Optional[str]:
    settings = get_settings()
    if not getattr(settings, "ocr_preprocess_enabled", False):
        return None
    prefix = getattr(settings, "ocr_preprocess_prefix", "preprocessed/ocr/")
    return preprocess_image_url(
        url,
        prefix=prefix,
        timeout_seconds=float(getattr(settings, "ocr_preprocess_timeout_seconds", 20.0)),
        max_bytes=int(getattr(settings, "ocr_preprocess_max_bytes", 20 * 1024 * 1024)),
    )
