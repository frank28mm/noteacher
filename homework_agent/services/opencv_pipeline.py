from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

try:
    import numpy as np
    import cv2

    _CV_AVAILABLE = True
except Exception:
    np = None  # type: ignore
    cv2 = None  # type: ignore
    _CV_AVAILABLE = False

from homework_agent.models.schemas import ImageRef
from homework_agent.utils.supabase_client import get_storage_client
from homework_agent.utils.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class OpenCVSliceResult:
    page_bytes: bytes
    figure_bytes: Optional[bytes]
    question_bytes: Optional[bytes]
    diagram_bbox: Optional[Tuple[int, int, int, int]]
    warnings: List[str]


def _strip_data_uri(data: str) -> str:
    if "," in data:
        return data.split(",", 1)[1]
    return data


def _load_image_bytes(ref: ImageRef, *, timeout_seconds: float, max_bytes: int) -> Optional[bytes]:
    if ref.url:
        try:
            with httpx.Client(timeout=timeout_seconds, follow_redirects=True, trust_env=False) as client:
                r = client.get(str(ref.url))
            if r.status_code != 200:
                return None
            data = r.content or b""
            if not data or len(data) > max_bytes:
                return None
            return data
        except Exception:
            return None
    if ref.base64:
        try:
            raw = _strip_data_uri(ref.base64)
            data = base64.b64decode(raw.encode("ascii"))
            if not data or len(data) > max_bytes:
                return None
            return data
        except Exception:
            return None
    return None


def _encode_jpeg(img: Any, *, quality: int = 90) -> Optional[bytes]:
    try:
        ok, encoded = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        if not ok:
            return None
        return encoded.tobytes()
    except Exception:
        return None


def _preprocess_gray(img: Any) -> Any:
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
    return thresh


def _deskew_image(img: Any) -> Any:
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thresh > 0))
        if coords.size == 0:
            return img
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        (h, w) = img.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            img,
            M,
            (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return rotated
    except Exception:
        return img


def _detect_diagram_roi(img: Any) -> Optional[Tuple[int, int, int, int]]:
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        h, w = gray.shape[:2]
        min_area = 0.05 * h * w
        max_area = 0.9 * h * w
        best = None
        best_area = 0.0
        for c in contours:
            x, y, cw, ch = cv2.boundingRect(c)
            area = float(cw * ch)
            if area < min_area or area > max_area:
                continue
            if area > best_area:
                best_area = area
                best = (x, y, cw, ch)
        return best
    except Exception:
        return None


def _crop(img: Any, bbox: Tuple[int, int, int, int]) -> Any:
    x, y, w, h = bbox
    return img[y : y + h, x : x + w]


def run_opencv_pipeline(ref: ImageRef) -> Optional[OpenCVSliceResult]:
    settings = get_settings()
    timeout_s = float(getattr(settings, "opencv_processing_timeout", 30))
    max_bytes = int(getattr(settings, "opencv_processing_max_bytes", 20 * 1024 * 1024))
    if not _CV_AVAILABLE:
        return None

    raw = _load_image_bytes(ref, timeout_seconds=timeout_s, max_bytes=max_bytes)
    if not raw:
        return None

    try:
        buf = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            return None
    except Exception:
        return None

    warnings: List[str] = []
    img = _deskew_image(img)
    bw = _preprocess_gray(img)
    page_bytes = _encode_jpeg(bw) or raw

    bbox = _detect_diagram_roi(img)
    figure_bytes = None
    question_bytes = None
    if bbox:
        try:
            fig = _crop(img, bbox)
            fig_gray = _preprocess_gray(fig)
            figure_bytes = _encode_jpeg(fig_gray)
        except Exception:
            warnings.append("diagram_roi_crop_failed")
    else:
        warnings.append("diagram_roi_not_found")

    # question slice defaults to full page (preprocessed)
    question_bytes = page_bytes
    return OpenCVSliceResult(
        page_bytes=page_bytes,
        figure_bytes=figure_bytes,
        question_bytes=question_bytes,
        diagram_bbox=bbox,
        warnings=warnings,
    )


def upload_slices(
    *,
    slices: OpenCVSliceResult,
    prefix: str,
) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {"page_url": None, "figure_url": None, "question_url": None}
    try:
        storage = get_storage_client()
    except Exception as e:
        logger.debug(f"upload_slices no storage: {e}")
        return out

    if slices.page_bytes:
        try:
            out["page_url"] = storage.upload_bytes(
                slices.page_bytes, mime_type="image/jpeg", suffix=".jpg", prefix=prefix
            )
        except Exception as e:
            logger.debug(f"upload page slice failed: {e}")
    if slices.figure_bytes:
        try:
            out["figure_url"] = storage.upload_bytes(
                slices.figure_bytes, mime_type="image/jpeg", suffix=".jpg", prefix=prefix
            )
        except Exception as e:
            logger.debug(f"upload figure slice failed: {e}")
    if slices.question_bytes:
        try:
            out["question_url"] = storage.upload_bytes(
                slices.question_bytes, mime_type="image/jpeg", suffix=".jpg", prefix=prefix
            )
        except Exception as e:
            logger.debug(f"upload question slice failed: {e}")
    return out
