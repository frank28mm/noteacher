"""
SiliconFlow question locator for qindex (BBox only).

Why:
- DeepSeek-OCR is good at extracting text but does not reliably return bbox coordinates.
- For qindex slicing we only need per-question regions (bbox) to crop slices.

Approach:
- Use a multimodal vision model (default: settings.silicon_vision_model / Qwen3-VL)
- Ask it to output a small strict JSON with question_number + normalized bbox.

Provider notes:
- Historically this locator was SiliconFlow-only. In practice, you may want to run the locator
  on Ark (Doubao) for better diagram/layout robustness.
- We keep the public surface area stable by selecting provider based on the configured model name:
  - model startswith "doubao-" -> use Ark `responses.create`
  - otherwise -> use SiliconFlow `chat.completions.create`
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI
from PIL import Image

from homework_agent.utils.observability import log_event, redact_url
from homework_agent.utils.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class QIndexLocateResult:
    text: str
    raw: Dict[str, Any]
    questions: List[
        Dict[str, Any]
    ]  # {question_number, regions:[{kind,bbox_norm_xyxy}]}


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    s = str(text).strip()
    if not s:
        return None

    # Strip code fences
    s = re.sub(r"^```(?:json)?\\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\\s*```\\s*$", "", s)

    # Robust extraction: find the first balanced JSON object, tolerate extra prose/trailing junk.
    def _balanced_objects(src: str):
        in_str = False
        esc = False
        depth = 0
        start_idx = None
        for i, ch in enumerate(src):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                if depth == 0:
                    start_idx = i
                depth += 1
                continue
            if ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start_idx is not None:
                        yield src[start_idx : i + 1]
                        start_idx = None
                continue

    candidates = 0
    last_err: Optional[str] = None
    for candidate in _balanced_objects(s):
        candidates += 1
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception as e:
            last_err = f"{e.__class__.__name__}: {e}"
            continue
    if last_err:
        log_event(
            logger,
            "qindex_locator_parse_failed",
            level="warning",
            text_len=len(s),
            candidates=candidates,
            error_type="json_parse_failed",
            error=last_err,
        )
    return None


def _to_float(x: Any) -> Optional[float]:
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x.strip())
        except Exception:
            return None
    return None


def _image_url_to_data_url(
    image_url: str, *, max_side: int = 1600, jpeg_quality: int = 85
) -> Optional[str]:
    """
    Convert a remote http(s) image URL to a compact JPEG data URL.

    Motivation:
      Some providers (notably Ark/Doubao `responses.create`) may fail with:
        "Timeout while fetching image_url"
      even if the URL is publicly accessible. Sending a data URL avoids the
      provider-side fetch.
    """
    if not image_url:
        return None
    u = str(image_url).strip()
    if not u:
        return None
    if u.startswith("data:"):
        return u
    if not (u.startswith("http://") or u.startswith("https://")):
        return None

    try:
        import httpx
    except Exception as e:
        log_event(
            logger,
            "qindex_data_url_httpx_import_failed",
            level="warning",
            image_url=redact_url(u),
            error_type=e.__class__.__name__,
            error=str(e),
        )
        return None

    try:
        r = httpx.get(u, timeout=30.0, follow_redirects=True)
        r.raise_for_status()
        data = r.content
        if not data:
            return None
    except Exception as e:
        log_event(
            logger,
            "qindex_data_url_download_failed",
            level="warning",
            image_url=redact_url(u),
            error_type=e.__class__.__name__,
            error=str(e),
        )
        return None

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        log_event(
            logger,
            "qindex_data_url_decode_failed",
            level="warning",
            image_url=redact_url(u),
            error_type=e.__class__.__name__,
            error=str(e),
        )
        return None

    try:
        # Downscale to reduce payload size (bbox localization tolerates this well).
        w, h = img.size
        if max(w, h) > int(max_side):
            ratio = float(max_side) / float(max(w, h))
            nw = max(1, int(round(w * ratio)))
            nh = max(1, int(round(h * ratio)))
            img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=int(jpeg_quality), optimize=True)
        b64 = base64.b64encode(out.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        log_event(
            logger,
            "qindex_data_url_encode_failed",
            level="warning",
            image_url=redact_url(u),
            error_type=e.__class__.__name__,
            error=str(e),
        )
        return None


class SiliconFlowQIndexLocator:
    def __init__(self) -> None:
        settings = get_settings()
        # SiliconFlow (OpenAI-compatible chat.completions)
        self.silicon_api_key = settings.silicon_api_key
        self.silicon_base_url = settings.silicon_base_url

        # Ark (OpenAI SDK responses.create)
        self.ark_api_key = settings.ark_api_key
        self.ark_base_url = settings.ark_base_url

        # Provider-specific locator model choices.
        self.silicon_model = (
            getattr(settings, "silicon_qindex_model", None)
            or settings.silicon_vision_model
        )
        self.ark_model = (
            getattr(settings, "ark_qindex_model", None) or settings.ark_vision_model
        )

        # Prefer Ark when ARK_QINDEX_MODEL is explicitly set to a Doubao vision model.
        self.model = (
            self.ark_model
            if str(self.ark_model or "").strip().lower().startswith("doubao-")
            else self.silicon_model
        )
        self.timeout_seconds = int(
            getattr(settings, "ark_qindex_timeout_seconds", 180)
            if self._provider() == "ark"
            else getattr(settings, "silicon_qindex_timeout_seconds", 180)
        )
        self.max_tokens = int(
            getattr(settings, "ark_qindex_max_tokens", 900)
            if self._provider() == "ark"
            else getattr(settings, "silicon_qindex_max_tokens", 900)
        )

    def _provider(self) -> str:
        m = str(self.model or "").strip()
        return "ark" if m.lower().startswith("doubao-") else "siliconflow"

    def is_configured(self) -> bool:
        if not self.model:
            return False
        if self._provider() == "ark":
            return bool(self.ark_api_key and self.ark_base_url)
        return bool(self.silicon_api_key and self.silicon_base_url)

    def _client(self) -> OpenAI:
        if self._provider() == "ark":
            return OpenAI(
                base_url=self.ark_base_url,
                api_key=self.ark_api_key,
                timeout=float(self.timeout_seconds),
            )
        return OpenAI(
            base_url=self.silicon_base_url,
            api_key=self.silicon_api_key,
            timeout=float(self.timeout_seconds),
        )

    def _prompt(self, *, only_question_numbers: Optional[List[str]] = None) -> str:
        only = ""
        if only_question_numbers:
            cleaned = [str(x).strip() for x in only_question_numbers if str(x).strip()]
            if cleaned:
                only = "仅定位这些题号：" + ", ".join(cleaned[:60]) + "。\\n"
        parts = [
            "你是一个“题目定位(OCR+版面分析)”引擎。只做定位，不要解题。\\n",
            "目标：在整页作业图片中，定位每一道题（题干+学生作答区域）的整体范围。\\n",
            only,
            "\\n",
            "请仅输出严格 JSON（不要 Markdown，不要代码块，不要解释文字）。\\n",
            "JSON 结构：{version, questions}\\n",
            "- version: 2\\n",
            "- questions: 数组，每项 {question_number, regions}\\n",
            '  - question_number: 字符串，如 "27"、"28(1)"、"20(2)"、"21①"。\\n',
            "  - regions: 数组，每项 {kind, bbox}\\n",
            '    - kind: "question" 或 "figure"。\\n',
            "    - bbox: 归一化坐标 [xmin, ymin, xmax, ymax]，范围 0~1。\\n",
            "      - kind=question：覆盖题干+作答。\\n",
            "      - kind=figure：覆盖该题所需的图示/函数图像/几何图形（如存在）。\\n",
            "\\n",
            "要求：\\n",
            "1) 【必须】返回所有题号，每题**必须**至少返回 1 个 kind=question 的 bbox。\\n",
            "2) 【重要】对于几何/图形题（含如图、角、平行、垂直、三角形等），**必须同时返回 kind=figure 的 bbox**，即使图形很小也要返回。\\n",
            "3) 若发现“共享图示区”集中放图（例如图下面写“第1题图/第2题图/...”），请为相应题号返回 kind=figure bbox。\\n",
            "4) bbox 允许略大，但尽量不要跨到另一题；figure bbox 允许更大一些，确保图示完整。\\n",
            "5) 按阅读顺序排序（从上到下、从左到右）。\\n",
            "6) 仅返回 JSON。\\n",
        ]
        return "".join(parts)

    def locate(
        self, *, image_url: str, only_question_numbers: Optional[List[str]] = None
    ) -> QIndexLocateResult:
        if not self.is_configured():
            raise RuntimeError(
                "qindex locator not configured (check SILICON_* or ARK_* env + ARK_QINDEX_MODEL/SILICON_QINDEX_MODEL)"
            )
        if not image_url:
            raise ValueError("image_url is required")

        client = self._client()
        prompt = self._prompt(only_question_numbers=only_question_numbers)
        t0 = time.monotonic()

        provider = self._provider()
        log_event(
            logger,
            "qindex_locate_start",
            provider=provider,
            model=self.model,
            image_url=redact_url(image_url),
        )

        def _call_ark(image_src: str) -> tuple[str, Dict[str, Any]]:
            content_blocks = [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_src},
            ]
            resp = client.responses.create(
                model=self.model,
                input=[{"role": "user", "content": content_blocks}],
            )
            raw0 = resp.to_dict()
            parts0: List[str] = []
            for item in getattr(resp, "output", []) or []:
                for c in getattr(item, "content", []) or []:
                    if getattr(c, "type", None) == "output_text":
                        parts0.append(getattr(c, "text", "") or "")
            return "\n".join([p for p in parts0 if p]), raw0

        def _call_silicon() -> tuple[str, Dict[str, Any]]:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
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
                log_event(
                    logger,
                    "qindex_locate_response_format_unsupported",
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
                content = "".join(str(x) for x in content)
            text0 = content if isinstance(content, str) else str(content)
            return text0, resp.to_dict()

        # Provider-side image_url fetch is sometimes flaky (e.g. "Timeout while fetching image_url").
        # For Ark, fall back to a local data-url to bypass provider-side fetching.
        text = ""
        raw: Dict[str, Any] = {}
        data_url: Optional[str] = None
        attempts = 3 if provider == "ark" else 2
        for i in range(attempts):
            try:
                if provider == "ark":
                    src = data_url or image_url
                    text, raw = _call_ark(src)
                else:
                    text, raw = _call_silicon()
                break
            except Exception as e:
                msg = str(e)
                fetch_timeout = (
                    "Timeout while fetching image_url" in msg
                    or "timeout while fetching image_url" in msg
                    # Ark sometimes returns 400 with this message when it can't download the public URL.
                    or "Timeout while downloading url=" in msg
                    or "timeout while downloading url=" in msg
                )
                if provider == "ark" and fetch_timeout and data_url is None:
                    data_url = _image_url_to_data_url(image_url)
                    log_event(
                        logger,
                        "qindex_locate_retry_data_url",
                        provider=provider,
                        model=self.model,
                        image_url=redact_url(image_url),
                        data_url=bool(data_url),
                    )
                    if data_url:
                        # Immediately retry with data URL.
                        continue

                # Only retry for known transient fetch/timeout patterns.
                transient = fetch_timeout or any(
                    s in msg
                    for s in (
                        "Read timed out",
                        "ReadTimeout",
                        "ConnectTimeout",
                        "APIConnectionError",
                    )
                )
                if not transient or i >= attempts - 1:
                    raise
                time.sleep(2.0 * (i + 1))

        obj = _extract_json(text)
        if obj is None:
            log_event(
                logger,
                "qindex_locate_parse_failed",
                provider=provider,
                model=self.model,
                text_len=len(text or ""),
                preview=(text or "")[:280],
            )
            questions: List[Dict[str, Any]] = []
        else:
            questions = []
            raw_qs = obj.get("questions")
            if isinstance(raw_qs, list):
                for q in raw_qs:
                    if not isinstance(q, dict):
                        continue
                    qn = q.get("question_number")
                    if not isinstance(qn, str) or not qn.strip():
                        continue
                    regions_out: List[Dict[str, Any]] = []
                    raw_regions = q.get("regions")
                    # Backward compat: accept single bbox field.
                    if raw_regions is None and q.get("bbox") is not None:
                        raw_regions = [{"kind": "question", "bbox": q.get("bbox")}]
                    if isinstance(raw_regions, list):
                        for r in raw_regions:
                            if not isinstance(r, dict):
                                continue
                            kind = r.get("kind")
                            kind_s = str(kind).strip().lower()
                            if kind_s not in ("question", "figure"):
                                # default to question
                                kind_s = "question"
                            bbox = r.get("bbox")
                            coords: Optional[List[float]] = None
                            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                                vals = [_to_float(v) for v in bbox]
                                if all(v is not None for v in vals):
                                    coords = [float(v) for v in vals]  # type: ignore[list-item]
                            if not coords:
                                continue
                            xmin, ymin, xmax, ymax = coords
                            regions_out.append(
                                {
                                    "kind": kind_s,
                                    "bbox_norm_xyxy": [xmin, ymin, xmax, ymax],
                                }
                            )
                    if not regions_out:
                        continue
                    questions.append(
                        {
                            "question_number": qn.strip(),
                            "regions": regions_out,
                        }
                    )

        log_event(
            logger,
            "qindex_locate_done",
            provider=provider,
            model=self.model,
            questions=len(questions),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            ok=bool(questions),
        )

        return QIndexLocateResult(text=text, raw=raw, questions=questions)
