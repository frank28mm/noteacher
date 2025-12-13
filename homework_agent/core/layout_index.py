"""
Question layout indexing (BBox + Slice).

Given:
- page_image_url(s) (public URLs)
- OCR layout blocks (text + bbox)

We produce:
- per-question bbox list (normalized [ymin,xmin,ymax,xmax])
- optional slice_image_url(s) (cropped uploads to Supabase)

MVP constraints:
- bbox covers whole question area (stem + work)
- may be larger, should not cross to other questions too much
- multi-page/cross-page: per-page indexing; cross-page can fall back to page-level
- failures: bbox/slice can be None; write warnings
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx
from PIL import Image

from homework_agent.utils.settings import get_settings
from homework_agent.utils.supabase_client import get_storage_client


QuestionNumber = str
BBoxPx = Tuple[float, float, float, float]  # xmin, ymin, xmax, ymax


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _bbox_union(a: Optional[BBoxPx], b: Optional[BBoxPx]) -> Optional[BBoxPx]:
    if a is None:
        return b
    if b is None:
        return a
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return (min(ax0, bx0), min(ay0, by0), max(ax1, bx1), max(ay1, by1))


def _px_to_norm_bbox(b: BBoxPx, width: int, height: int) -> List[float]:
    x0, y0, x1, y1 = b
    if width <= 0 or height <= 0:
        return [0.0, 0.0, 1.0, 1.0]
    ymin = _clamp01(y0 / height)
    xmin = _clamp01(x0 / width)
    ymax = _clamp01(y1 / height)
    xmax = _clamp01(x1 / width)
    return [ymin, xmin, ymax, xmax]


def _apply_padding_norm(b: List[float], pad_ratio: float) -> List[float]:
    ymin, xmin, ymax, xmax = b
    h = max(0.0, ymax - ymin)
    w = max(0.0, xmax - xmin)
    pad_y = h * pad_ratio
    pad_x = w * pad_ratio
    return [
        _clamp01(ymin - pad_y),
        _clamp01(xmin - pad_x),
        _clamp01(ymax + pad_y),
        _clamp01(xmax + pad_x),
    ]


def _norm_to_px_bbox(b: List[float], width: int, height: int) -> BBoxPx:
    ymin, xmin, ymax, xmax = b
    x0 = int(max(0, min(width, round(xmin * width))))
    y0 = int(max(0, min(height, round(ymin * height))))
    x1 = int(max(0, min(width, round(xmax * width))))
    y1 = int(max(0, min(height, round(ymax * height))))
    if x1 <= x0:
        x1 = min(width, x0 + 1)
    if y1 <= y0:
        y1 = min(height, y0 + 1)
    return (x0, y0, x1, y1)


def _extract_text(block: Dict[str, Any]) -> str:
    for k in ("text", "words", "word", "content"):
        v = block.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list):
            parts = [str(p).strip() for p in v if str(p).strip()]
            if parts:
                return " ".join(parts)
    return ""


def _extract_bbox_px(block: Dict[str, Any]) -> Optional[BBoxPx]:
    """
    Best-effort bbox extraction from common shapes:
    - location: {left, top, width, height}
    - bbox: [x0,y0,x1,y1] or {xmin,ymin,xmax,ymax}
    - polygon/points: list of {x,y} or [x,y]
    """
    loc = block.get("location") or block.get("loc")
    if isinstance(loc, dict):
        left = loc.get("left")
        top = loc.get("top")
        w = loc.get("width")
        h = loc.get("height")
        if all(isinstance(v, (int, float)) for v in (left, top, w, h)):
            return (float(left), float(top), float(left + w), float(top + h))

    bbox = block.get("bbox") or block.get("box") or block.get("rect")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4 and all(
        isinstance(v, (int, float)) for v in bbox
    ):
        x0, y0, x1, y1 = bbox
        return (float(x0), float(y0), float(x1), float(y1))
    if isinstance(bbox, dict):
        x0 = bbox.get("xmin") or bbox.get("left")
        y0 = bbox.get("ymin") or bbox.get("top")
        x1 = bbox.get("xmax") or bbox.get("right")
        y1 = bbox.get("ymax") or bbox.get("bottom")
        if all(isinstance(v, (int, float)) for v in (x0, y0, x1, y1)):
            return (float(x0), float(y0), float(x1), float(y1))
        w = bbox.get("width")
        h = bbox.get("height")
        if all(isinstance(v, (int, float)) for v in (x0, y0, w, h)):
            return (float(x0), float(y0), float(x0 + w), float(y0 + h))

    pts = block.get("polygon") or block.get("points") or block.get("vertices")
    if isinstance(pts, list) and pts:
        xs: List[float] = []
        ys: List[float] = []
        for p in pts:
            if isinstance(p, dict):
                x = p.get("x")
                y = p.get("y")
            elif isinstance(p, (list, tuple)) and len(p) >= 2:
                x, y = p[0], p[1]
            else:
                continue
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                xs.append(float(x))
                ys.append(float(y))
        if xs and ys:
            return (min(xs), min(ys), max(xs), max(ys))

    return None


_QNUM_RE = re.compile(r"^\s*(?:第\s*)?(\d{1,3}(?:\(\d+\))?(?:[①②③④⑤⑥⑦⑧⑨])?)\s*[题\.、:：]?\s*")


def _detect_question_number(text: str) -> Optional[QuestionNumber]:
    if not text:
        return None
    m = _QNUM_RE.match(text)
    if not m:
        return None
    return m.group(1)


@dataclass
class QuestionLayout:
    question_number: QuestionNumber
    bboxes_norm: List[List[float]]  # list of [ymin,xmin,ymax,xmax]
    slice_image_urls: List[str]
    warnings: List[str]


def build_question_layouts_from_blocks(
    *,
    blocks: List[Dict[str, Any]],
    page_width: int,
    page_height: int,
    padding_ratio: float,
) -> Dict[QuestionNumber, QuestionLayout]:
    """
    Group OCR blocks into question-level bounding boxes by detecting question-number anchors.
    """
    # Convert blocks to rows sorted by top-left y
    rows: List[Tuple[float, Dict[str, Any], str, Optional[BBoxPx], Optional[QuestionNumber]]] = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        text = _extract_text(b)
        bbox = _extract_bbox_px(b)
        qn = _detect_question_number(text)
        y = bbox[1] if bbox else 0.0
        rows.append((y, b, text, bbox, qn))
    rows.sort(key=lambda x: x[0])

    q_to_bbox: Dict[QuestionNumber, Optional[BBoxPx]] = {}
    current_q: Optional[QuestionNumber] = None
    for _, _, text, bbox, qn in rows:
        if qn:
            current_q = qn
            q_to_bbox.setdefault(current_q, None)
        if current_q and bbox:
            q_to_bbox[current_q] = _bbox_union(q_to_bbox[current_q], bbox)

    layouts: Dict[QuestionNumber, QuestionLayout] = {}
    for qn, bbox_px in q_to_bbox.items():
        warnings: List[str] = []
        if bbox_px is None:
            warnings.append("定位不确定，改用整页")
            layouts[qn] = QuestionLayout(qn, bboxes_norm=[], slice_image_urls=[], warnings=warnings)
            continue
        bbox_norm = _px_to_norm_bbox(bbox_px, page_width, page_height)
        bbox_norm = _apply_padding_norm(bbox_norm, padding_ratio)
        layouts[qn] = QuestionLayout(qn, bboxes_norm=[bbox_norm], slice_image_urls=[], warnings=warnings)
    return layouts


def download_image(url: str, timeout: float = 30.0) -> Image.Image:
    # Avoid local proxy interference for public object downloads (supabase/public URLs etc.).
    # If you rely on system proxies for other traffic, keep them for API calls, but downloads
    # used for bbox/slice should be direct.
    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGB")


def crop_and_upload_slices(
    *,
    page_image_url: str,
    layouts: Dict[QuestionNumber, QuestionLayout],
    prefix: str = "slices/",
) -> Dict[QuestionNumber, QuestionLayout]:
    """
    For each question bbox, crop and upload to Supabase and populate slice_image_urls.
    """
    settings = get_settings()
    storage = get_storage_client()
    img = download_image(page_image_url)
    width, height = img.size
    for qn, layout in layouts.items():
        if not layout.bboxes_norm:
            continue
        slice_urls: List[str] = []
        for b_norm in layout.bboxes_norm:
            bbox_px = _norm_to_px_bbox(b_norm, width, height)
            crop = img.crop(bbox_px)
            out = io.BytesIO()
            crop.save(out, format="JPEG", quality=90)
            url = storage.upload_bytes(
                out.getvalue(),
                mime_type="image/jpeg",
                suffix=".jpg",
                prefix=prefix,
            )
            slice_urls.append(url)
        layout.slice_image_urls = slice_urls
        if not slice_urls:
            layout.warnings.append("切片生成失败，改用整页")
    return layouts
