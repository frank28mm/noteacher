from __future__ import annotations

import ast
import base64
import hashlib
import httpx
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from io import BytesIO
from typing import Any, Dict, List, Optional

try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

import sympy

from homework_agent.models.schemas import ImageRef, VisionProvider
from homework_agent.services.opencv_pipeline import run_opencv_pipeline, upload_slices
from homework_agent.services.vision import VisionClient
from homework_agent.services.qindex_locator_siliconflow import SiliconFlowQIndexLocator
from homework_agent.core.layout_index import crop_and_upload_slices, QuestionLayout
from homework_agent.api.session import get_question_index
from homework_agent.core.prompts_autonomous import OCR_FALLBACK_PROMPT, PROMPT_VERSION
from homework_agent.utils.settings import get_settings
from homework_agent.utils.cache import get_cache_store
from homework_agent.utils.supabase_client import get_storage_client

logger = logging.getLogger(__name__)

# Cache keys
OCR_CACHE_PREFIX = "ocr_cache:"
SLICE_FAILED_CACHE_PREFIX = "slice_failed:"
QINDEX_CACHE_PREFIX = "qindex_slices:"
OCR_CACHE_TTL = 86400  # 24 hours
SLICE_FAILED_CACHE_TTL = 3600  # 1 hour
QINDEX_CACHE_TTL = 3600  # 1 hour


def _annotate_tool_signals(*, tool_name: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add stable, machine-readable tool signals without breaking existing callers.

    We keep original keys (status/message/urls/text/etc.) and only append:
      - ok: bool
      - needs_review: bool
      - warning_codes: list[str]
      - retryable: bool
      - error_type/error_code (best-effort)

    This is used for observability + HITL triggers; it must never raise.
    """
    try:
        if not isinstance(result, dict):
            return {
                "status": "error",
                "message": "tool_result_not_dict",
                "ok": False,
                "needs_review": True,
                "warning_codes": [f"tool_error:{tool_name}"],
                "retryable": False,
            }  # noqa: E501

        status = str(result.get("status") or "").strip().lower()
        message = str(result.get("message") or result.get("warning") or "").strip()

        warning_codes: List[str] = []
        needs_review = False
        retryable = False
        error_code: Optional[str] = None
        error_type: Optional[str] = None

        if status in {"error"}:
            needs_review = True
            warning_codes.append(f"tool_error:{tool_name}")
            if "timeout" in message.lower():
                error_code = "timeout"
                retryable = True
            elif "rate" in message.lower() or "429" in message:
                error_code = "rate_limited"
                retryable = True
            elif (
                "not configured" in message.lower()
                or "not_configured" in message.lower()
            ):
                error_code = "not_configured"
                retryable = False
            else:
                error_code = "tool_failed"
            error_type = str(result.get("error_type") or "ToolError")

        elif status in {"degraded"}:
            # Degraded is successful but should be surfaced for review/analysis.
            warning_codes.append(f"tool_degraded:{tool_name}")
            # Only force needs_review on high-signal degradation reasons.
            msg_l = message.lower()
            if any(
                k in msg_l
                for k in ("fallback", "roi_not_found", "diagram_roi_not_found")
            ):
                needs_review = True
                warning_codes.append("evidence_degraded")

        elif status in {"empty"}:
            warning_codes.append(f"tool_empty:{tool_name}")

        # Domain-specific signals: diagram roi failure is a strong HITL trigger.
        try:
            warnings = result.get("warnings") or []
            if isinstance(warnings, list) and any(
                "diagram_roi_not_found" in str(w) for w in warnings
            ):
                warning_codes.append("diagram_roi_not_found")
                needs_review = True
        except Exception:
            pass
        if "diagram_roi_not_found" in message:
            warning_codes.append("diagram_roi_not_found")
            needs_review = True

        # Keep any existing codes provided by the tool.
        existing_codes = result.get("warning_codes")
        if isinstance(existing_codes, list):
            for c in existing_codes:
                cs = str(c).strip()
                if cs:
                    warning_codes.append(cs)

        # Safety scan (PII / prompt-injection markers): always triggers HITL.
        try:
            from homework_agent.security.safety import scan_safety

            scan = scan_safety(result)
            if scan.warning_codes:
                warning_codes.extend(scan.warning_codes)
                needs_review = needs_review or bool(scan.needs_review)
        except Exception:
            pass

        # De-dup, preserve order.
        seen = set()
        deduped: List[str] = []
        for c in warning_codes:
            if c in seen:
                continue
            seen.add(c)
            deduped.append(c)

        ok = status in {"ok", "degraded", "empty"}
        result.setdefault("ok", bool(ok))
        result.setdefault("needs_review", bool(needs_review))
        result.setdefault("warning_codes", deduped)
        result.setdefault("retryable", bool(retryable))
        if error_code:
            result.setdefault("error_code", error_code)
        if error_type:
            result.setdefault("error_type", error_type)
        return result
    except Exception:
        # Last resort: do not break tool caller.
        return (
            result
            if isinstance(result, dict)
            else {"status": "error", "message": "tool_signal_annotation_failed"}
        )


def _as_imageref(value: str) -> ImageRef:
    if value.startswith("data:image/"):
        return ImageRef(base64=value)
    return ImageRef(url=value)


def _build_ocr_cache_key(*, img_hash: str, provider: str, prompt_version: str) -> str:
    safe_provider = (provider or "unknown").strip() or "unknown"
    safe_version = (prompt_version or "v1").strip() or "v1"
    return f"{OCR_CACHE_PREFIX}{img_hash}:{safe_provider}:{safe_version}"


def _compute_image_hash(image_url_or_base64: str) -> Optional[str]:
    """Download image and compute content hash (SHA256).
    Using content hash instead of URL hash to support same content with different URLs.
    """
    try:
        if image_url_or_base64.startswith("data:image/"):
            # Base64: decode and hash
            if "," in image_url_or_base64:
                data = base64.b64decode(image_url_or_base64.split(",", 1)[1])
            else:
                data = base64.b64decode(image_url_or_base64)
            return hashlib.sha256(data).hexdigest()
        else:
            # URL: download and hash
            settings = get_settings()
            timeout = float(getattr(settings, "opencv_processing_timeout", 30))
            with httpx.Client(
                timeout=timeout, follow_redirects=True, trust_env=False
            ) as client:
                r = client.get(image_url_or_base64)
                if r.status_code == 200:
                    return hashlib.sha256(r.content).hexdigest()
            return None
    except Exception as e:
        logger.debug(f"Failed to compute image hash: {e}")
        return None


def _compress_image_if_needed(image_url: str, max_side: int = 1280) -> str:
    """Compress image if it exceeds max_side. Returns new URL or original URL."""
    if not PIL_AVAILABLE:
        return image_url

    if image_url.startswith("data:image/"):
        return image_url  # Skip base64

    try:
        # Download image
        settings = get_settings()
        timeout = float(getattr(settings, "opencv_processing_timeout", 30))
        with httpx.Client(
            timeout=timeout, follow_redirects=True, trust_env=False
        ) as client:
            r = client.get(image_url)
            if r.status_code != 200:
                return image_url

        # Check dimensions
        img = Image.open(BytesIO(r.content))
        w, h = img.size
        if max(w, h) <= max_side:
            return image_url  # No compression needed

        # Compress
        if w > h:
            new_w, new_h = max_side, int(h * max_side / w)
        else:
            new_w, new_h = int(w * max_side / h), max_side

        compressed = img.resize((new_w, new_h), Image.LANCZOS)
        buffer = BytesIO()
        compressed.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        # Upload compressed version
        storage = get_storage_client()
        compressed_url = storage.upload_bytes(
            file_content=buffer.getvalue(),
            mime_type="image/jpeg",
            suffix=".jpg",
            prefix="compressed/",
        )
        logger.info(
            f"Compressed image from {w}x{h} to {new_w}x{new_h}: {compressed_url}"
        )
        return compressed_url
    except Exception as e:
        logger.debug(f"Failed to compress image: {e}")
        return image_url


def diagram_slice(*, image: str, prefix: str) -> Dict[str, Any]:
    """Run OpenCV pipeline to slice diagram and question regions.
    P0.3: Cache failures using image_hash to avoid repeated attempts.
    """
    # Check cache for previous failures
    img_hash = _compute_image_hash(image)
    if img_hash:
        cache = get_cache_store()
        cache_key = f"{SLICE_FAILED_CACHE_PREFIX}{img_hash}"
        cached_failure = cache.get(cache_key)
        if cached_failure:
            logger.info(f"diagram_slice: Cached failure for {img_hash[:8]}...")
            return _annotate_tool_signals(
                tool_name="diagram_slice",
                result={
                    "status": "error",
                    "message": "diagram_roi_not_found",
                    "reason": "roi_not_found",
                    "cached": True,
                },
            )

    ref = _as_imageref(image)
    slices = run_opencv_pipeline(ref)
    if not slices:
        return _annotate_tool_signals(
            tool_name="diagram_slice",
            result={
                "status": "error",
                "message": "opencv_pipeline_failed",
                "reason": "opencv_pipeline_failed",
            },
        )

    # Cache roi_not_found failures
    if slices.warnings and "diagram_roi_not_found" in slices.warnings:
        if img_hash:
            cache = get_cache_store()
            cache_key = f"{SLICE_FAILED_CACHE_PREFIX}{img_hash}"
            cache.set(cache_key, "1", ttl_seconds=SLICE_FAILED_CACHE_TTL)
            logger.info(f"Cached diagram_slice failure for {img_hash[:8]}...")

    reason = None
    if slices.warnings and "diagram_roi_not_found" in slices.warnings:
        reason = "roi_not_found"

    urls = upload_slices(slices=slices, prefix=prefix)
    return _annotate_tool_signals(
        tool_name="diagram_slice",
        result={
            "status": "ok",
            "urls": urls,
            "warnings": slices.warnings,
            "reason": reason,
        },
    )


def qindex_fetch(*, session_id: str) -> Dict[str, Any]:
    """Fetch question index from session.
    P2.1: Cache qindex slices to avoid repeated fetches.
    """
    if not session_id:
        return _annotate_tool_signals(
            tool_name="qindex_fetch",
            result={"status": "error", "message": "session_id_missing"},
        )

    # Check cache
    cache = get_cache_store()
    cache_key = f"{QINDEX_CACHE_PREFIX}{session_id}"
    cached = cache.get(cache_key)
    if cached:
        logger.info(f"qindex_fetch: Cache hit for session {session_id}")
        return {
            "status": "ok",
            "questions": cached.get("questions") or {},
            "warnings": cached.get("warnings") or [],
            "cached": True,
        }

    # Fetch from session
    qindex = get_question_index(session_id)
    if not qindex:
        return _annotate_tool_signals(
            tool_name="qindex_fetch",
            result={"status": "empty", "questions": {}, "warnings": ["qindex_empty"]},
        )

    result = _annotate_tool_signals(
        tool_name="qindex_fetch",
        result={
            "status": "ok",
            "questions": qindex.get("questions") or {},
            "warnings": qindex.get("warnings") or [],
        },
    )

    # Cache result
    cache.set(cache_key, result, ttl_seconds=QINDEX_CACHE_TTL)
    logger.info(f"Cached qindex result for session {session_id}")

    return result


def vision_roi_detect(*, image: str, prefix: str) -> Dict[str, Any]:
    """Use VLM locator to detect figure/question regions and upload slices.
    Returns a unified regions list aligned with qindex_fetch structure.
    """
    locator = SiliconFlowQIndexLocator()
    if not locator.is_configured():
        return _annotate_tool_signals(
            tool_name="vision_roi_detect",
            result={"status": "error", "message": "locator_not_configured"},
        )

    image_url = str(image or "").strip()
    if not image_url:
        return _annotate_tool_signals(
            tool_name="vision_roi_detect",
            result={"status": "error", "message": "image_missing"},
        )

    try:
        loc = locator.locate(image_url=image_url, only_question_numbers=None)
    except Exception as e:
        return _annotate_tool_signals(
            tool_name="vision_roi_detect",
            result={
                "status": "error",
                "message": str(e),
                "error_type": e.__class__.__name__,
            },
        )

    if not loc.questions:
        return _annotate_tool_signals(
            tool_name="vision_roi_detect",
            result={"status": "empty", "regions": [], "warning": "no_questions"},
        )

    # Build layouts and kind mapping
    layouts: Dict[str, QuestionLayout] = {}
    region_kinds: Dict[str, List[str]] = {}
    for q in loc.questions:
        qn = q.get("question_number")
        regions = q.get("regions")
        if not isinstance(qn, str) or not qn.strip():
            continue
        if not isinstance(regions, list) or not regions:
            continue
        qn_s = qn.strip()
        bboxes_norm: List[List[float]] = []
        kinds: List[str] = []
        for r in regions:
            if not isinstance(r, dict):
                continue
            kind = str(r.get("kind") or "question").strip().lower()
            if kind not in ("question", "figure"):
                kind = "question"
            bbox = r.get("bbox_norm_xyxy")
            if not (
                isinstance(bbox, (list, tuple))
                and len(bbox) == 4
                and all(isinstance(v, (int, float)) for v in bbox)
            ):
                continue
            xmin, ymin, xmax, ymax = [float(v) for v in bbox]
            xmin = max(0.0, min(1.0, xmin))
            ymin = max(0.0, min(1.0, ymin))
            xmax = max(0.0, min(1.0, xmax))
            ymax = max(0.0, min(1.0, ymax))
            bboxes_norm.append([ymin, xmin, ymax, xmax])
            kinds.append(kind)

        if not bboxes_norm:
            continue

        layouts[qn_s] = QuestionLayout(
            question_number=qn_s,
            bboxes_norm=bboxes_norm,
            slice_image_urls=[],
            warnings=[],
        )
        region_kinds[qn_s] = kinds

    if not layouts:
        return _annotate_tool_signals(
            tool_name="vision_roi_detect",
            result={"status": "empty", "regions": [], "warning": "no_regions"},
        )

    # Crop and upload slices
    try:
        layouts = crop_and_upload_slices(
            page_image_url=image_url,
            layouts=layouts,
            only_question_numbers=None,
            prefix=prefix,
        )
    except Exception as e:
        return _annotate_tool_signals(
            tool_name="vision_roi_detect",
            result={
                "status": "error",
                "message": f"slice_upload_failed: {e}",
                "error_type": e.__class__.__name__,
            },
        )

    regions_out: List[Dict[str, Any]] = []
    for qn, layout in layouts.items():
        kinds = region_kinds.get(qn, [])
        for i, url in enumerate(layout.slice_image_urls or []):
            if not url:
                continue
            kind = kinds[i] if i < len(kinds) else "question"
            bbox_norm = (
                layout.bboxes_norm[i] if i < len(layout.bboxes_norm or []) else None
            )
            regions_out.append(
                {
                    "kind": kind,
                    "bbox_norm_xyxy": bbox_norm,
                    "slice_url": url,
                }
            )

    return _annotate_tool_signals(
        tool_name="vision_roi_detect",
        result={"status": "ok", "regions": regions_out, "warning": None},
    )


ALLOWED_SYMPY_FUNCS = {"simplify", "expand", "solve", "factor", "sympify"}


def _run_sympy(expr: str) -> Any:
    return sympy.simplify(sympy.sympify(expr))


def math_verify(*, expression: str) -> Dict[str, Any]:
    """Verify mathematical expression using sympy sandbox."""
    cleaned = (expression or "").replace("\n", "").strip()
    if not cleaned:
        return _annotate_tool_signals(
            tool_name="math_verify",
            result={"status": "error", "message": "empty_expression"},
        )
    if any(x in cleaned for x in ("__", "import", "exec", "eval", "open")):
        return _annotate_tool_signals(
            tool_name="math_verify",
            result={"status": "error", "message": "forbidden_token"},
        )

    try:
        tree = ast.parse(cleaned, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = getattr(node.func, "id", "")
                if func_name not in ALLOWED_SYMPY_FUNCS:
                    return _annotate_tool_signals(
                        tool_name="math_verify",
                        result={"status": "error", "message": "forbidden_function"},
                    )
    except Exception as e:
        return _annotate_tool_signals(
            tool_name="math_verify",
            result={
                "status": "error",
                "message": f"parse_error: {e}",
                "error_type": e.__class__.__name__,
            },
        )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_sympy, cleaned)
            result = future.result(timeout=5)
        return _annotate_tool_signals(
            tool_name="math_verify", result={"status": "ok", "result": str(result)}
        )
    except FutureTimeout:
        return _annotate_tool_signals(
            tool_name="math_verify",
            result={"status": "error", "message": "Expression evaluation timeout"},
        )
    except Exception as e:
        return _annotate_tool_signals(
            tool_name="math_verify",
            result={
                "status": "error",
                "message": str(e),
                "error_type": e.__class__.__name__,
            },
        )


def ocr_fallback(*, image: str, provider: str) -> Dict[str, Any]:
    """OCR fallback using Vision API.
    P0.1: Cache OCR results using image content hash.
    """
    # Check cache
    img_hash = _compute_image_hash(image)
    if img_hash:
        cache = get_cache_store()
        cache_key = _build_ocr_cache_key(
            img_hash=img_hash,
            provider=str(provider or "unknown"),
            prompt_version=PROMPT_VERSION,
        )
        cached = cache.get(cache_key)
        if cached:
            logger.info(f"ocr_fallback: Cache hit for {img_hash[:8]}...")
            return _annotate_tool_signals(
                tool_name="ocr_fallback",
                result={
                    "status": "ok",
                    "text": cached,
                    "source": "cache",
                },
            )

    ref = _as_imageref(image)
    vision_provider = (
        VisionProvider.QWEN3 if provider == "silicon" else VisionProvider.DOUBAO
    )
    client = VisionClient()
    try:
        result = client.analyze(
            images=[ref], prompt=OCR_FALLBACK_PROMPT, provider=vision_provider
        )
    except Exception as e:
        return _annotate_tool_signals(
            tool_name="ocr_fallback",
            result={
                "status": "error",
                "message": str(e),
                "error_type": e.__class__.__name__,
            },
        )

    text = (result.text or "").strip()
    if not text:
        return _annotate_tool_signals(
            tool_name="ocr_fallback", result={"status": "empty", "text": ""}
        )

    # Cache result
    if img_hash:
        cache = get_cache_store()
        cache_key = _build_ocr_cache_key(
            img_hash=img_hash,
            provider=str(provider or "unknown"),
            prompt_version=PROMPT_VERSION,
        )
        cache.set(cache_key, text, ttl_seconds=OCR_CACHE_TTL)
        logger.info(f"Cached OCR result for {img_hash[:8]}...")

    return _annotate_tool_signals(
        tool_name="ocr_fallback", result={"status": "ok", "text": text}
    )
