from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from homework_agent.core.prompts import (
    VISION_GRADE_SYSTEM_PROMPT_MATH,
    VISION_GRADE_SYSTEM_PROMPT_ENGLISH,
)
from homework_agent.models.schemas import Subject, ImageRef
from homework_agent.services.llm import LLMClient, _repair_json_text
from homework_agent.services.opencv_pipeline import run_opencv_pipeline, upload_slices
from homework_agent.utils.settings import get_settings
from homework_agent.utils.observability import log_event, log_llm_usage, trace_span
from homework_agent.utils.versioning import stable_json_hash, stable_text_hash

logger = logging.getLogger(__name__)


class UnifiedGradePayload(BaseModel):
    status: Optional[str] = None
    reason: Optional[str] = None
    ocr_text: Optional[str] = None
    results: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


@dataclass
class UnifiedGradeResult:
    status: str
    reason: Optional[str]
    ocr_text: str
    results: List[Dict[str, Any]]
    summary: str
    warnings: List[str]


def _normalize_verdict(v: Any) -> str:
    s = str(v or "").strip().lower()
    if s in {"correct", "incorrect", "uncertain"}:
        return s
    if s in {"wrong", "error"}:
        return "incorrect"
    return "uncertain"


def _ensure_judgment_basis(result: Dict[str, Any], *, min_len: int) -> None:
    basis = result.get("judgment_basis")
    if not isinstance(basis, list) or not basis:
        result["judgment_basis"] = ["依据来源：仅OCR文本（图像细节不清晰）"]
        return
    has_source = any(isinstance(b, str) and "依据来源" in b for b in basis)
    if not has_source:
        result["judgment_basis"] = ["依据来源：OCR+图像理解"] + [
            b for b in basis if isinstance(b, str)
        ]
    # Ensure minimum length
    if min_len > 0 and len(result["judgment_basis"]) < min_len:
        result["judgment_basis"] = result["judgment_basis"] + ["依据题干与作答进行判断"]


def _select_prompt(subject: Subject) -> str:
    if subject == Subject.ENGLISH:
        return VISION_GRADE_SYSTEM_PROMPT_ENGLISH
    return VISION_GRADE_SYSTEM_PROMPT_MATH


def _parse_unified_json(text: str) -> Optional[UnifiedGradePayload]:
    if not text:
        return None
    raw = str(text)
    try:
        data = json.loads(raw)
        return UnifiedGradePayload.model_validate(data)
    except Exception:
        repaired = _repair_json_text(raw)
        if not repaired:
            return None
        try:
            data = json.loads(repaired)
            return UnifiedGradePayload.model_validate(data)
        except Exception:
            return None


def _repair_with_llm(
    *,
    llm: LLMClient,
    provider: str,
    raw_text: str,
    error: str,
    max_tokens: int,
) -> Optional[UnifiedGradePayload]:
    prompt = (
        "你是 JSON 修复器。请将下方内容修复为严格 JSON，只输出 JSON，不要解释。\n"
        f"解析错误：{error}\n\n"
        f"原始内容：\n{raw_text}\n"
    )
    resp = llm.generate(
        prompt=prompt, provider=provider, max_tokens=max_tokens, temperature=0.0
    )
    return _parse_unified_json(resp.text or "")


def _build_user_prompt() -> str:
    return (
        "请基于图片进行作业识别与批改。"
        "你能直接看图并完成识别、理解与判定。"
        "若不是作业/试卷图片，直接返回 status=rejected。"
    )


def _prepare_image_inputs(
    *,
    images: List[ImageRef],
    session_id: str,
) -> Tuple[List[ImageRef], List[str]]:
    prefix = f"preprocessed/grade/{session_id}/"
    final_refs: List[ImageRef] = []
    warnings: List[str] = []

    for ref in images:
        slices = run_opencv_pipeline(ref)
        if not slices:
            # fallback to original
            final_refs.append(ref)
            continue
        urls = upload_slices(slices=slices, prefix=prefix)
        if slices.warnings:
            warnings.extend(slices.warnings)

        if urls.get("figure_url") and urls.get("question_url"):
            final_refs.append(ImageRef(url=urls["figure_url"]))
            final_refs.append(ImageRef(url=urls["question_url"]))
        elif urls.get("question_url"):
            final_refs.append(ImageRef(url=urls["question_url"]))
        elif urls.get("page_url"):
            final_refs.append(ImageRef(url=urls["page_url"]))
        else:
            final_refs.append(ref)

        # Limit to reduce context bloat (2 images per page).
        if len(final_refs) >= 4:
            break

    return final_refs or images, warnings


@trace_span("vision_grade_agent.run")
async def run_unified_grade_agent(
    *,
    images: List[ImageRef],
    subject: Subject,
    provider: str,
    session_id: str,
    request_id: Optional[str],
) -> UnifiedGradeResult:
    settings = get_settings()
    llm = LLMClient()
    prompt = _select_prompt(subject)
    user_prompt = _build_user_prompt()

    max_tokens = int(getattr(settings, "unified_agent_max_tokens", 1600))
    timeout_s = float(getattr(settings, "unified_agent_timeout_seconds", 600))
    repair_attempts = int(getattr(settings, "json_repair_max_attempts", 1))

    thresholds = {
        "timeout_seconds": timeout_s,
        "max_tokens_per_call": max_tokens,
        "json_repair_max_attempts": repair_attempts,
    }
    thresholds_hash = stable_json_hash(thresholds)[:16]
    try:
        model = (
            llm.silicon_vision_model if provider == "silicon" else llm.ark_vision_model
        )
    except Exception:
        model = None
    prompt_id = f"unified.{str(getattr(subject, 'value', subject))}"
    prompt_version = stable_text_hash(prompt)[:16]
    log_event(
        logger,
        "run_versions",
        session_id=session_id,
        request_id=request_id,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        provider=provider,
        model=str(model or ""),
        thresholds=thresholds,
        thresholds_hash=thresholds_hash,
    )

    prep_start = time.monotonic()
    log_event(
        logger,
        "unified_agent_preprocess_start",
        request_id=request_id,
        session_id=session_id,
        images=len(images or []),
    )
    refs, cv_warnings = await asyncio.to_thread(
        _prepare_image_inputs, images=images, session_id=session_id
    )
    log_event(
        logger,
        "unified_agent_preprocess_done",
        request_id=request_id,
        session_id=session_id,
        images_in=len(images or []),
        images_out=len(refs or []),
        warnings_count=len(cv_warnings or []),
        elapsed_ms=int((time.monotonic() - prep_start) * 1000),
    )

    log_event(
        logger,
        "unified_agent_start",
        request_id=request_id,
        session_id=session_id,
        provider=provider,
        subject=str(getattr(subject, "value", subject)),
        images=len(refs),
    )

    async def _call_llm():
        return llm.generate_with_images(
            system_prompt=prompt,
            user_prompt=user_prompt,
            images=refs,
            provider=provider,
            max_tokens=max_tokens,
            temperature=0.2,
            use_tools=True,
        )

    llm_start = time.monotonic()
    log_event(
        logger,
        "unified_agent_llm_start",
        request_id=request_id,
        session_id=session_id,
        provider=provider,
        max_tokens=max_tokens,
        images=len(refs),
    )
    try:
        res = await asyncio.wait_for(_call_llm(), timeout=timeout_s)
    except Exception as e:
        log_event(
            logger,
            "unified_agent_llm_failed",
            level="warning",
            request_id=request_id,
            session_id=session_id,
            error_type=e.__class__.__name__,
            error=str(e),
            elapsed_ms=int((time.monotonic() - llm_start) * 1000),
        )
        raise RuntimeError(f"unified_agent_failed: {e}") from e

    try:
        log_llm_usage(
            logger,
            request_id=str(request_id or ""),
            session_id=str(session_id or ""),
            provider=str(provider or ""),
            model=str(
                llm.silicon_vision_model
                if provider == "silicon"
                else llm.ark_vision_model
            ),
            usage=getattr(res, "usage", None) or {},
            stage="unified.llm",
        )
    except Exception:
        pass

    log_event(
        logger,
        "unified_agent_llm_done",
        request_id=request_id,
        session_id=session_id,
        elapsed_ms=int((time.monotonic() - llm_start) * 1000),
        raw_len=len(getattr(res, "text", "") or ""),
    )

    parse_path = "fail"
    repaired_json = False
    payload: Optional[UnifiedGradePayload] = None
    raw = str(getattr(res, "text", "") or "")
    try:
        data = json.loads(raw)
        payload = UnifiedGradePayload.model_validate(data)
        parse_path = "json"
    except Exception:
        repaired = _repair_json_text(raw)
        if repaired:
            try:
                data = json.loads(repaired)
                payload = UnifiedGradePayload.model_validate(data)
                parse_path = "repair"
                repaired_json = True
            except Exception:
                payload = None

    attempts_left = repair_attempts
    while payload is None and attempts_left > 0:
        attempts_left -= 1
        payload = _repair_with_llm(
            llm=llm,
            provider=provider,
            raw_text=raw,
            error="json_parse_failed",
            max_tokens=max_tokens,
        )
        if payload is not None:
            parse_path = "repair_llm"
            repaired_json = True

    log_event(
        logger,
        "unified_agent_parse",
        request_id=request_id,
        session_id=session_id,
        parse_path=parse_path,
        repaired_json=repaired_json,
        attempts_used=int(repair_attempts - attempts_left),
    )

    if payload is None:
        raise RuntimeError("unified_agent_parse_failed")

    status = (payload.status or "done").strip().lower()
    if status == "rejected":
        log_event(
            logger,
            "unified_agent_rejected",
            request_id=request_id,
            session_id=session_id,
            reason=payload.reason or "not_homework",
        )
        return UnifiedGradeResult(
            status="rejected",
            reason=payload.reason or "not_homework",
            ocr_text=payload.ocr_text or "",
            results=[],
            summary="输入非作业图片，已拒绝批改",
            warnings=payload.warnings,
        )

    results: List[Dict[str, Any]] = []
    min_len = int(getattr(get_settings(), "judgment_basis_min_length", 2))
    for r in payload.results or []:
        if not isinstance(r, dict):
            continue
        copy_r = dict(r)
        copy_r["verdict"] = _normalize_verdict(copy_r.get("verdict"))
        _ensure_judgment_basis(copy_r, min_len=min_len)
        results.append(copy_r)

    summary = payload.summary or "批改完成"
    warnings = list(payload.warnings or [])
    warnings.extend(cv_warnings)

    log_event(
        logger,
        "unified_agent_done",
        request_id=request_id,
        session_id=session_id,
        results=len(results),
        warnings_count=len(warnings),
    )
    return UnifiedGradeResult(
        status="done",
        reason=None,
        ocr_text=payload.ocr_text or "",
        results=results,
        summary=summary,
        warnings=warnings,
    )
