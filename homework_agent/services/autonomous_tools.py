from __future__ import annotations

import ast
import base64
import hashlib
import httpx
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from io import BytesIO
from typing import Any, Dict, Optional

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

import sympy

from homework_agent.models.schemas import ImageRef, VisionProvider
from homework_agent.services.opencv_pipeline import run_opencv_pipeline, upload_slices
from homework_agent.services.vision import VisionClient
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
            with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
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
        with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
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
        logger.info(f"Compressed image from {w}x{h} to {new_w}x{new_h}: {compressed_url}")
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
            return {
                "status": "error",
                "message": "diagram_roi_not_found",
                "cached": True,
            }

    ref = _as_imageref(image)
    slices = run_opencv_pipeline(ref)
    if not slices:
        return {"status": "error", "message": "opencv_pipeline_failed"}

    # Cache roi_not_found failures
    if slices.warnings and "diagram_roi_not_found" in slices.warnings:
        if img_hash:
            cache = get_cache_store()
            cache_key = f"{SLICE_FAILED_CACHE_PREFIX}{img_hash}"
            cache.set(cache_key, "1", ttl_seconds=SLICE_FAILED_CACHE_TTL)
            logger.info(f"Cached diagram_slice failure for {img_hash[:8]}...")

    urls = upload_slices(slices=slices, prefix=prefix)
    return {"status": "ok", "urls": urls, "warnings": slices.warnings}


def qindex_fetch(*, session_id: str) -> Dict[str, Any]:
    """Fetch question index from session.
    P2.1: Cache qindex slices to avoid repeated fetches.
    """
    if not session_id:
        return {"status": "error", "message": "session_id_missing"}

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
        return {"status": "empty", "questions": {}, "warnings": ["qindex_empty"]}

    result = {
        "status": "ok",
        "questions": qindex.get("questions") or {},
        "warnings": qindex.get("warnings") or [],
    }

    # Cache result
    cache.set(cache_key, result, ttl_seconds=QINDEX_CACHE_TTL)
    logger.info(f"Cached qindex result for session {session_id}")

    return result


ALLOWED_SYMPY_FUNCS = {"simplify", "expand", "solve", "factor", "sympify"}


def _run_sympy(expr: str) -> Any:
    return sympy.simplify(sympy.sympify(expr))


def math_verify(*, expression: str) -> Dict[str, Any]:
    """Verify mathematical expression using sympy sandbox."""
    cleaned = (expression or "").replace("\n", "").strip()
    if not cleaned:
        return {"status": "error", "message": "empty_expression"}
    if any(x in cleaned for x in ("__", "import", "exec", "eval", "open")):
        return {"status": "error", "message": "forbidden_token"}

    try:
        tree = ast.parse(cleaned, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = getattr(node.func, "id", "")
                if func_name not in ALLOWED_SYMPY_FUNCS:
                    return {"status": "error", "message": "forbidden_function"}
    except Exception as e:
        return {"status": "error", "message": f"parse_error: {e}"}

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_sympy, cleaned)
            result = future.result(timeout=5)
        return {"status": "ok", "result": str(result)}
    except FutureTimeout:
        return {"status": "error", "message": "Expression evaluation timeout"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


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
            return {
                "status": "ok",
                "text": cached,
                "source": "cache",
            }

    ref = _as_imageref(image)
    settings = get_settings()
    vision_provider = VisionProvider.QWEN3 if provider == "silicon" else VisionProvider.DOUBAO
    client = VisionClient()
    try:
        result = client.analyze(images=[ref], prompt=OCR_FALLBACK_PROMPT, provider=vision_provider)
    except Exception as e:
        return {"status": "error", "message": str(e)}

    text = (result.text or "").strip()
    if not text:
        return {"status": "empty", "text": ""}

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

    return {"status": "ok", "text": text}
