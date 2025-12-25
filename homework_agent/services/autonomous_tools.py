from __future__ import annotations

import base64
from typing import Any, Dict, Optional

from homework_agent.models.schemas import ImageRef, VisionProvider
from homework_agent.services.opencv_pipeline import run_opencv_pipeline, upload_slices
from homework_agent.services.vision import VisionClient
from homework_agent.api.session import get_question_index
from homework_agent.core.prompts_autonomous import OCR_FALLBACK_PROMPT
from homework_agent.utils.settings import get_settings

import ast
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import sympy


def _as_imageref(value: str) -> ImageRef:
    if value.startswith("data:image/"):
        return ImageRef(base64=value)
    return ImageRef(url=value)


def diagram_slice(*, image: str, prefix: str) -> Dict[str, Any]:
    ref = _as_imageref(image)
    slices = run_opencv_pipeline(ref)
    if not slices:
        return {"status": "error", "message": "opencv_pipeline_failed"}
    urls = upload_slices(slices=slices, prefix=prefix)
    return {"status": "ok", "urls": urls, "warnings": slices.warnings}


def qindex_fetch(*, session_id: str) -> Dict[str, Any]:
    if not session_id:
        return {"status": "error", "message": "session_id_missing"}
    qindex = get_question_index(session_id)
    if not qindex:
        return {"status": "empty", "questions": {}, "warnings": ["qindex_empty"]}
    return {"status": "ok", "questions": qindex.get("questions") or {}, "warnings": qindex.get("warnings") or []}


ALLOWED_SYMPY_FUNCS = {"simplify", "expand", "solve", "factor", "sympify"}


def _run_sympy(expr: str) -> Any:
    return sympy.simplify(sympy.sympify(expr))


def math_verify(*, expression: str) -> Dict[str, Any]:
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
    return {"status": "ok", "text": text}
