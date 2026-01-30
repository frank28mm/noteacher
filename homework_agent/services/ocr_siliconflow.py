"""
SiliconFlow OCR client (DeepSeek-OCR via OpenAI-compatible chat completions).

Goal:
- Provide OCR text blocks with bbox so qindex can build per-question layouts/slices.

Notes:
- This is best-effort. We ask the model to return strict JSON. If parsing fails, we return [].
- Prefer public URL. If the provider cannot fetch the URL, fallback to data URI (base64).
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import OpenAI

from homework_agent.utils.settings import get_settings
from homework_agent.utils.observability import log_event, redact_url

logger = logging.getLogger(__name__)


@dataclass
class SiliconFlowOCRResult:
    text: str
    raw: Dict[str, Any]
    blocks: List[Dict[str, Any]]


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract the first JSON object from a model response.
    Handles common wrappers like ```json ... ``` or leading/trailing prose.
    """
    if not text:
        return None
    s = str(text).strip()
    if not s:
        return None

    # Strip code fences
    # - handle leading fences
    s = re.sub(r"^```(?:json)?\\s*", "", s, flags=re.IGNORECASE)
    # - handle trailing fences
    s = re.sub(r"\\s*```\\s*$", "", s)

    # Find a JSON object boundaries (best-effort)
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = s[start : end + 1].strip()
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _as_data_uri(url: str, *, timeout_seconds: float) -> Optional[str]:
    """Download image bytes and convert to a data URI for image_url input."""
    if not url:
        return None
    try:
        with httpx.Client(
            timeout=timeout_seconds, follow_redirects=True, trust_env=False
        ) as client:
            r = client.get(url)
            r.raise_for_status()
            ct = (r.headers.get("content-type") or "image/jpeg").split(";")[
                0
            ].strip() or "image/jpeg"
            data = r.content or b""
        settings = get_settings()
        max_bytes = int(getattr(settings, "max_upload_image_bytes", 5 * 1024 * 1024))
        if not data or len(data) > max_bytes:
            return None
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{ct};base64,{b64}"
    except Exception as e:
        log_event(
            logger,
            "silicon_ocr_data_uri_download_failed",
            level="warning",
            image_url=redact_url(url),
            error_type=e.__class__.__name__,
            error=str(e),
        )
        return None


class SiliconFlowDeepSeekOCRClient:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.silicon_api_key
        self.base_url = settings.silicon_base_url
        self.model = settings.silicon_ocr_model
        self.timeout_seconds = int(settings.silicon_ocr_timeout_seconds)
        self.max_tokens = int(settings.silicon_ocr_max_tokens)

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def _build_client(self) -> OpenAI:
        return OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=float(self.timeout_seconds),
        )

    def _prompt(self) -> str:
        """
        IMPORTANT:
        We keep output small and stable. For qindex we only need question-level regions,
        not full-page OCR. Large OCR outputs frequently get truncated and become invalid JSON.
        """
        # bbox is normalized [xmin,ymin,xmax,ymax] in 0..1 range.
        return (
            "你是一个“题目定位(OCR+版面分析)”引擎。只做定位，不要解题。\\n"
            "目标：在整页作业图片中，找出每一道题（题干+作答区域）的整体范围。\\n"
            "\\n"
            "请仅输出严格 JSON（不要 Markdown，不要代码块，不要解释文字）。\\n"
            "JSON 结构：{version, questions}\\n"
            "- version: 1\\n"
            "- questions: 数组，每项 {question_number, bbox}\\n"
            '  - question_number: 字符串，如 "27"、"28(1)"、"20(2)"、"21①"（尽量沿用图片上的题号写法）\\n'
            "  - bbox: 归一化坐标 [xmin, ymin, xmax, ymax]，范围 0~1；bbox 要覆盖该题“题干+学生作答”。\\n"
            "\\n"
            "要求：\\n"
            "1) 必须尽量返回所有题号（不确定也返回 best-effort）。\\n"
            "2) bbox 允许略大，但尽量不要跨到另一题。\\n"
            "3) 按阅读顺序排序（从上到下、从左到右）。\\n"
            "4) 仅返回 JSON。\\n"
            "\\n"
            "输出示例：\\n"
            "{"
            '"version":1,'
            '"questions":['
            '{"question_number":"20(2)","bbox":[0.05,0.10,0.95,0.25]},'
            '{"question_number":"21(1)","bbox":[0.05,0.26,0.95,0.40]}'
            "]"
            "}"
        )

    def analyze(self, *, image_url: str) -> SiliconFlowOCRResult:
        if not self.is_configured():
            raise RuntimeError(
                "SILICON_API_KEY/SILICON_BASE_URL/SILICON_OCR_MODEL not configured"
            )
        if not image_url:
            raise ValueError("image_url is required")

        client = self._build_client()
        prompt = self._prompt()

        def _call(url: str) -> Tuple[str, Dict[str, Any]]:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                }
            ]
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=0,
                    response_format={"type": "json_object"},
                )
            except Exception as e:
                # Some OpenAI-compatible servers may not support response_format yet.
                log_event(
                    logger,
                    "silicon_ocr_response_format_unsupported",
                    level="warning",
                    provider="siliconflow",
                    model=self.model,
                    error_type=e.__class__.__name__,
                    error=str(e),
                )
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=0,
                )

            content = resp.choices[0].message.content if resp.choices else ""
            if isinstance(content, list):
                # Best-effort join for non-standard SDK responses.
                content = "".join(str(x) for x in content)
            text = content if isinstance(content, str) else str(content)
            return text or "", resp.to_dict()

        t0 = time.monotonic()
        log_event(
            logger,
            "silicon_ocr_start",
            provider="siliconflow",
            model=self.model,
            image_url=redact_url(image_url),
        )
        text, raw = _call(image_url)

        # If parsing fails, try data-URI fallback (avoids server-side URL fetch).
        obj = _extract_json_object(text)
        if obj is None:
            log_event(
                logger,
                "silicon_ocr_parse_failed",
                provider="siliconflow",
                model=self.model,
                text_len=len(text or ""),
                preview=(text or "")[:280],
            )
            data_uri = _as_data_uri(
                image_url, timeout_seconds=float(self.timeout_seconds)
            )
            if data_uri:
                log_event(
                    logger,
                    "silicon_ocr_retry_data_uri",
                    provider="siliconflow",
                    model=self.model,
                    image_url=redact_url(image_url),
                )
                text, raw = _call(data_uri)
                obj = _extract_json_object(text)
                if obj is None:
                    log_event(
                        logger,
                        "silicon_ocr_parse_failed",
                        provider="siliconflow",
                        model=self.model,
                        text_len=len(text or ""),
                        preview=(text or "")[:280],
                        stage="data_uri",
                    )

        blocks: List[Dict[str, Any]] = []
        if isinstance(obj, dict):
            # Accept either {blocks:[{text,bbox}]} or {questions:[{question_number,bbox}]}.
            raw_blocks = obj.get("blocks")
            if not isinstance(raw_blocks, list):
                raw_blocks = obj.get("questions")

            def _to_float(x: Any) -> Optional[float]:
                if isinstance(x, (int, float)):
                    return float(x)
                if isinstance(x, str):
                    try:
                        return float(x.strip())
                    except Exception:
                        return None
                return None

            if isinstance(raw_blocks, list):
                for b in raw_blocks:
                    if not isinstance(b, dict):
                        continue
                    qn = b.get("question_number")
                    txt = b.get("text")
                    bbox = b.get("bbox")

                    label = None
                    if isinstance(qn, str) and qn.strip():
                        label = qn.strip()
                    elif isinstance(txt, str) and txt.strip():
                        label = txt.strip()
                    if not label:
                        continue

                    coords: Optional[List[float]] = None
                    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                        vals = [_to_float(v) for v in bbox]
                        if all(v is not None for v in vals):
                            coords = [float(v) for v in vals]  # type: ignore[list-item]
                    elif isinstance(bbox, dict):
                        vals = [
                            _to_float(bbox.get(k))
                            for k in ("xmin", "ymin", "xmax", "ymax")
                        ]
                        if all(v is not None for v in vals):
                            coords = [float(v) for v in vals]  # type: ignore[list-item]

                    if not coords:
                        continue
                    xmin, ymin, xmax, ymax = coords
                    blocks.append(
                        {
                            "text": label,
                            "question_number": label,
                            "bbox_norm": [xmin, ymin, xmax, ymax],
                        }
                    )

        log_event(
            logger,
            "silicon_ocr_done",
            provider="siliconflow",
            model=self.model,
            blocks=len(blocks),
            text_len=len(text or ""),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            ok=bool(blocks),
        )

        return SiliconFlowOCRResult(text=text, raw=raw, blocks=blocks)
