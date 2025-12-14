from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Tuple
import re

from fastapi import APIRouter, HTTPException, status, Request, Header, BackgroundTasks

from homework_agent.models.schemas import (
    GradeRequest, GradeResponse,
    VisionProvider, Subject, SimilarityMode, ImageRef
)
from homework_agent.services.vision import VisionClient
from homework_agent.services.llm import LLMClient, MathGradingResult, EnglishGradingResult
from homework_agent.services.qindex_queue import enqueue_qindex_job
from homework_agent.utils.settings import get_settings
from homework_agent.core.qbank import (
    assign_stable_item_ids,
    build_question_bank,
    build_question_bank_from_vision_raw_text,
    dedupe_wrong_items,
    derive_wrong_items_from_questions,
    sanitize_wrong_items,
)
from homework_agent.api.session import (
    cache_store,
    save_mistakes,
    get_mistakes,
    save_question_index,
    persist_question_bank,
    _merge_bank_meta,
    _ensure_session_id,
    IDP_TTL_HOURS,
)
from homework_agent.utils.observability import get_request_id_from_headers, log_event

logger = logging.getLogger(__name__)

router = APIRouter()

# 并发保护：防止线程池堆积导致“越跑越慢/无响应”
_settings_for_limits = get_settings()
VISION_SEMAPHORE = asyncio.Semaphore(max(1, int(_settings_for_limits.max_concurrent_vision)))
LLM_SEMAPHORE = asyncio.Semaphore(max(1, int(_settings_for_limits.max_concurrent_llm)))

async def _call_blocking_in_thread(
    fn,
    *args,
    timeout_seconds: float,
    semaphore: asyncio.Semaphore,
    **kwargs,
):
    """Run a blocking function in a thread with a timeout + concurrency guard."""
    async with semaphore:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs),
            timeout=timeout_seconds,
        )

# 常量
# 取消硬性 5 轮上限；仅保留计数用于提示递进

def validate_vision_provider(provider: VisionProvider) -> VisionProvider:
    """验证vision_provider是否在白名单中"""
    allowed_providers = [VisionProvider.QWEN3, VisionProvider.DOUBAO]
    if provider not in allowed_providers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid vision_provider. Allowed values: {[p.value for p in allowed_providers]}"
        )
    return provider


def _is_public_url(url: str) -> bool:
    url = str(url)
    if not url:
        return False
    if re.match(r"^https?://", url) is None:
        return False
    if url.startswith("http://127.") or url.startswith("https://127."):
        return False
    if url.startswith("http://localhost") or url.startswith("https://localhost"):
        return False
    return True


def _strip_base64_prefix(data: str) -> str:
    return re.sub(r"^data:image/[^;]+;base64,", "", data, flags=re.IGNORECASE)


def _first_public_image_url(images: List[Any]) -> Optional[str]:
    for img in images or []:
        url = getattr(img, "url", None) or (img.get("url") if isinstance(img, dict) else None)
        if url:
            return str(url)
    return None


def _probe_url_head(url: str) -> Optional[str]:
    """Best-effort HEAD probe for debugging (status/content-type/content-length)."""
    if not url:
        return None
    try:
        import httpx

        # Don't inherit local proxy env for public URL probes.
        with httpx.Client(timeout=5.0, follow_redirects=True, trust_env=False) as client:
            r = client.head(url)
        ct = r.headers.get("content-type")
        cl = r.headers.get("content-length")
        return f"url_head status={r.status_code} content-type={ct} content-length={cl}"
    except Exception as e:
        return f"url_head probe_failed: {e}"


def _download_as_data_uri(url: str) -> Optional[str]:
    """Best-effort: download image bytes locally and convert to data URI for Qwen3 base64 fallback."""
    if not url:
        return None
    try:
        import httpx

        # Avoid local proxy interference when downloading public object URLs.
        with httpx.Client(timeout=20.0, follow_redirects=True, trust_env=False) as client:
            r = client.get(url)
        if r.status_code != 200:
            return None
        content_type = r.headers.get("content-type", "image/jpeg").split(";")[0].strip() or "image/jpeg"
        data = r.content or b""
        if not data:
            return None
        if len(data) > 20 * 1024 * 1024:
            return None
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{content_type};base64,{b64}"
    except Exception:
        return None


def validate_images_payload(images: List[Dict[str, Any]], vision_provider: VisionProvider) -> None:
    """Early validation for /grade to reduce invalid calls."""
    if not images:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Images cannot be empty")
    for img in images:
        url = img.get("url")
        b64 = img.get("base64")
        if url:
            if not _is_public_url(url):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Image URL must be public HTTP/HTTPS (no localhost/127)",
                )
        elif b64:
            cleaned = _strip_base64_prefix(b64)
            est_bytes = int(len(cleaned) * 0.75)
            if est_bytes > 20 * 1024 * 1024:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image size exceeds 20MB; use URL")
            if vision_provider == VisionProvider.DOUBAO:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Doubao only supports URL; base64 not accepted")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Each image must provide url or base64")


def generate_job_id() -> str:
    """生成任务ID"""
    return f"job_{uuid.uuid4().hex[:16]}"


def get_idempotency_key(request: Request, x_idempotency_key: Optional[str] = None) -> Optional[str]:
    """获取幂等性键，只接受 Header。"""
    if x_idempotency_key:
        return x_idempotency_key.strip()
    return None


def check_idempotency(idempotency_key: str) -> Optional[GradeResponse]:
    """检查幂等性，如果存在则返回缓存结果"""
    cached = cache_store.get(f"idp:{idempotency_key}")
    if not cached:
        return None
    try:
        return GradeResponse(**cached["response"])
    except Exception:
        return None


def cache_response(idempotency_key: str, response: GradeResponse) -> None:
    """缓存响应结果"""
    cache_store.set(
        f"idp:{idempotency_key}",
        {"response": response.model_dump(), "ts": datetime.now().isoformat()},
        ttl_seconds=IDP_TTL_HOURS * 3600,
    )


async def perform_grading(req: GradeRequest, provider_str: str) -> GradeResponse:
    """执行批改（同步/后台共用）。"""
    # 提前确定 session_id，用于所有返回路径（grade→chat 必须可续接）
    session_for_ctx = _ensure_session_id(req.session_id or req.batch_id)
    try:
        # Best-effort: keep request/session aligned for downstream job records.
        req.session_id = session_for_ctx
    except Exception:
        pass

    settings = get_settings()
    started = time.monotonic()
    deadline = started + float(settings.grade_completion_sla_seconds)
    timings_ms: Dict[str, int] = {}
    req_id = getattr(req, "_request_id", None)

    def remaining_seconds() -> float:
        return max(0.0, deadline - time.monotonic())

    vision_prompt = (
        "请识别并提取作业内容，包括题目、答案和解题步骤。逐题输出“学生作答状态”：若看到答案/勾选则写明，若未看到答案/空白/未勾选，明确标注“未作答”或“可能未作答”。"
        "选择题必须完整列出选项（A/B/C/D 每一项的原文），并明确学生选择了哪个选项；若未勾选，标注未作答。"
        "对含幂/分式/下标的公式请双写：先按原式抄写（含上下标、分式），再给出纯文本展开形式（如 10^(n+1)、(a-b)^2/(c+d)）。"
        "特别自检指数/分母的 +1、±、平方/立方等细节，如有疑似误读，直接在结果中标注“可能误读公式：…”。"
        "对“规律/序列/图示题”（含箭头/示例/表格/图形），必须先原样抄写题目给出的示例（例如 A→B→C→D→C→B 或对应数字位置），不要凭空推断；若示例在图中，请描述图中出现的字母/顺序/位置关系。"
        "注意：你只负责识别与抄录（OCR+结构化），不要进行解题/判定/推理，不要写出你推断的正确答案或规律（例如“应为6n+3”这类）。如果示例/图中信息没识别出来，请明确写“示例未识别到/看不清”，并在 warnings 中标注风险。"
    )

    vision_client = VisionClient()
    vision_fallback_warning: Optional[str] = None
    meta_base: Dict[str, Any] = {
        "vision_provider_requested": getattr(req.vision_provider, "value", str(req.vision_provider)),
        "vision_provider_used": None,
        "vision_used_base64_fallback": False,
        "llm_provider_requested": provider_str,
        "llm_provider_used": None,
        "llm_used_fallback": False,
    }

    # Vision stage (offload to thread + sub-timeout)
    v_budget = min(float(settings.grade_vision_timeout_seconds), remaining_seconds())
    log_event(
        logger,
        "grade_vision_budget",
        request_id=req_id,
        session_id=session_for_ctx,
        provider_requested=getattr(req.vision_provider, "value", str(req.vision_provider)),
        budget_s=v_budget,
    )
    if v_budget <= 0:
        # Persist minimal snapshot so chat can deterministically explain the failure.
        persist_question_bank(
            session_id=session_for_ctx,
            bank=_merge_bank_meta(
                {
                "session_id": session_for_ctx,
                "subject": req.subject.value if hasattr(req.subject, "value") else str(req.subject),
                "vision_raw_text": None,
                "page_image_urls": [str(img.url) for img in (req.images or []) if getattr(img, "url", None)],
                "questions": {},
                },
                meta_base,
            ),
            grade_status="failed",
            grade_summary="Vision analysis not available",
            grade_warnings=["grade SLA exceeded before vision started"],
            timings_ms=timings_ms,
        )
        return GradeResponse(
            wrong_items=[],
            summary="Vision analysis not available",
            subject=req.subject,
            job_id=None,
            session_id=session_for_ctx,
            status="failed",
            total_items=None,
            wrong_count=None,
            cross_subject_flag=None,
            warnings=["grade SLA exceeded before vision started"],
            vision_raw_text=None,
        )

    async def _run_vision(provider: VisionProvider, budget: float):
        return await _call_blocking_in_thread(
            vision_client.analyze,
            images=req.images,
            prompt=vision_prompt,
            provider=provider,
            timeout_seconds=budget,
            semaphore=VISION_SEMAPHORE,
        )

    def _vision_err_str(err: Exception, budget: float) -> str:
        if isinstance(err, asyncio.TimeoutError):
            return f"timeout after {int(budget)}s"
        s = str(err).strip()
        return s or err.__class__.__name__

    try:
        log_event(
            logger,
            "vision_start",
            request_id=req_id,
            session_id=session_for_ctx,
            provider=getattr(req.vision_provider, "value", str(req.vision_provider)),
            budget_s=v_budget,
        )
        v0 = time.monotonic()
        vision_result = await _run_vision(req.vision_provider, v_budget)
        timings_ms["vision_ms"] = int((time.monotonic() - v0) * 1000)
        meta_base["vision_provider_used"] = getattr(req.vision_provider, "value", str(req.vision_provider))
        log_event(
            logger,
            "vision_done",
            request_id=req_id,
            session_id=session_for_ctx,
            provider=meta_base.get("vision_provider_used"),
            vision_ms=timings_ms.get("vision_ms"),
            vision_text_len=len(getattr(vision_result, "text", "") or ""),
        )
    except Exception as e:
        log_event(
            logger,
            "vision_failed",
            level="warning",
            request_id=req_id,
            session_id=session_for_ctx,
            provider=getattr(req.vision_provider, "value", str(req.vision_provider)),
            error_type=e.__class__.__name__,
            error=str(e),
            budget_s=v_budget,
        )
        if req.vision_provider == VisionProvider.DOUBAO:
            probe = _probe_url_head(_first_public_image_url(req.images))
            # Fallback to qwen3 within remaining budget.
            v_budget2 = min(float(settings.grade_vision_timeout_seconds), remaining_seconds())
            if v_budget2 <= 0:
                persist_question_bank(
                    session_id=session_for_ctx,
                    bank=_merge_bank_meta(
                        {
                        "session_id": session_for_ctx,
                        "subject": req.subject.value if hasattr(req.subject, "value") else str(req.subject),
                        "vision_raw_text": None,
                        "page_image_urls": [str(img.url) for img in (req.images or []) if getattr(img, "url", None)],
                        "questions": {},
                        },
                        meta_base,
                    ),
                    grade_status="failed",
                    grade_summary="Vision analysis not available",
                    grade_warnings=[w for w in [
                        f"Vision(doubao) failed: {_vision_err_str(e, v_budget)}",
                        probe,
                        "grade SLA exceeded before vision fallback",
                    ] if w],
                    timings_ms=timings_ms,
                )
                return GradeResponse(
                    wrong_items=[],
                    summary="Vision analysis not available",
                    subject=req.subject,
                    job_id=None,
                    session_id=session_for_ctx,
                    status="failed",
                    total_items=None,
                    wrong_count=None,
                    cross_subject_flag=None,
                    warnings=[w for w in [
                        f"Vision(doubao) failed: {_vision_err_str(e, v_budget)}",
                        probe,
                        "grade SLA exceeded before vision fallback",
                    ] if w],
                    vision_raw_text=None,
                )
            try:
                # Strong fallback: if URL fetch is flaky for cloud providers, convert URLs to base64 locally for Qwen3.
                converted_images: List[Any] = []
                converted_any = False
                for img in req.images or []:
                    if getattr(img, "base64", None):
                        converted_images.append(img)
                        continue
                    url = getattr(img, "url", None)
                    if url:
                        data_uri = _download_as_data_uri(str(url))
                        if data_uri:
                            converted_any = True
                            converted_images.append(type(img)(base64=data_uri))
                        else:
                            converted_images.append(img)
                    else:
                        converted_images.append(img)

                if converted_any:
                    vision_result = await _call_blocking_in_thread(
                        vision_client.analyze,
                        images=converted_images,
                        prompt=vision_prompt,
                        provider=VisionProvider.QWEN3,
                        timeout_seconds=v_budget2,
                        semaphore=VISION_SEMAPHORE,
                    )
                else:
                    vision_result = await _run_vision(VisionProvider.QWEN3, v_budget2)
                meta_base["vision_provider_used"] = VisionProvider.QWEN3.value
                meta_base["vision_used_base64_fallback"] = bool(converted_any)
                log_event(
                    logger,
                    "vision_fallback_done",
                    request_id=req_id,
                    session_id=session_for_ctx,
                    provider=meta_base.get("vision_provider_used"),
                    used_base64=meta_base.get("vision_used_base64_fallback"),
                    vision_text_len=len(getattr(vision_result, "text", "") or ""),
                )
                vision_fallback_warning = (
                    f"Vision(doubao) 失败，已回退到 qwen3: {_vision_err_str(e, v_budget)}"
                    + (f"；{probe}" if probe else "")
                    + ("；qwen3 使用本地下载+base64 兜底" if converted_any else "")
                )
            except Exception as e2:
                log_event(
                    logger,
                    "vision_fallback_failed",
                    level="error",
                    request_id=req_id,
                    session_id=session_for_ctx,
                    provider="qwen3",
                    error_type=e2.__class__.__name__,
                    error=str(e2),
                    budget_s=v_budget2,
                )
                persist_question_bank(
                    session_id=session_for_ctx,
                    bank=_merge_bank_meta(
                        {
                        "session_id": session_for_ctx,
                        "subject": req.subject.value if hasattr(req.subject, "value") else str(req.subject),
                        "vision_raw_text": None,
                        "page_image_urls": [str(img.url) for img in (req.images or []) if getattr(img, "url", None)],
                        "questions": {},
                        },
                        meta_base,
                    ),
                    grade_status="failed",
                    grade_summary="Vision analysis not available",
                    grade_warnings=[w for w in [
                        f"Vision(doubao) failed: {_vision_err_str(e, v_budget)}",
                        probe,
                        f"Vision fallback (qwen3) also failed: {_vision_err_str(e2, v_budget2)}",
                    ] if w],
                    timings_ms=timings_ms,
                )
                return GradeResponse(
                    wrong_items=[],
                    summary="Vision analysis not available",
                    subject=req.subject,
                    job_id=None,
                    session_id=session_for_ctx,
                    status="failed",
                    total_items=None,
                    wrong_count=None,
                    cross_subject_flag=None,
                    warnings=[w for w in [
                        f"Vision(doubao) failed: {_vision_err_str(e, v_budget)}",
                        probe,
                        f"Vision fallback (qwen3) also failed: {_vision_err_str(e2, v_budget2)}",
                    ] if w],
                    vision_raw_text=None,
                )
        else:
            persist_question_bank(
                session_id=session_for_ctx,
                bank=_merge_bank_meta(
                    {
                    "session_id": session_for_ctx,
                    "subject": req.subject.value if hasattr(req.subject, "value") else str(req.subject),
                    "vision_raw_text": None,
                    "page_image_urls": [str(img.url) for img in (req.images or []) if getattr(img, "url", None)],
                    "questions": {},
                    },
                    meta_base,
                ),
                grade_status="failed",
                grade_summary="Vision analysis not available",
                grade_warnings=[f"Vision analysis failed: {_vision_err_str(e, v_budget)}"],
                timings_ms=timings_ms,
            )
            return GradeResponse(
                wrong_items=[],
                summary="Vision analysis not available",
                subject=req.subject,
                job_id=None,
                session_id=session_for_ctx,
                status="failed",
                total_items=None,
                wrong_count=None,
                cross_subject_flag=None,
                warnings=[f"Vision analysis failed: {_vision_err_str(e, v_budget)}"],
                vision_raw_text=None,
            )

    llm_client = LLMClient()

    def _needs_fallback(result: Any) -> bool:
        """Detect Ark grading failure that should fall back to Qwen3."""
        summary = (getattr(result, "summary", "") or "").strip()
        if summary.startswith("批改失败") or summary.startswith("批改结果解析失败"):
            return True
        warnings = getattr(result, "warnings", None) or []
        for w in warnings:
            w_str = str(w)
            if any(
                key in w_str
                # Note: don't treat "Parse error" as fatal here because we may have already fallen back to Qwen3,
                # and we still want to return a successful grading result if the fallback succeeded.
                for key in ("InvalidEndpointOrModel", "NotFound", "Error code")
            ):
                return True
        return False

    try:
        if req.subject == Subject.MATH:
            async def _grade_math(provider: str):
                b = min(float(settings.grade_llm_timeout_seconds), remaining_seconds())
                if b <= 0:
                    raise asyncio.TimeoutError(
                        f"grade SLA exceeded before LLM started (elapsed={int(time.monotonic()-started)}s)"
                    )
                return await _call_blocking_in_thread(
                    llm_client.grade_math,
                    text_content=vision_result.text,
                    provider=provider,
                    timeout_seconds=b,
                    semaphore=LLM_SEMAPHORE,
                )

            try:
                g0 = time.monotonic()
                log_event(
                    logger,
                    "grade_llm_start",
                    request_id=req_id,
                    session_id=session_for_ctx,
                    provider=provider_str,
                )
                grading_result = await _grade_math(provider_str)
                timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                meta_base["llm_provider_used"] = provider_str
                log_event(
                    logger,
                    "grade_llm_done",
                    request_id=req_id,
                    session_id=session_for_ctx,
                    provider=meta_base.get("llm_provider_used"),
                    llm_ms=timings_ms.get("llm_ms"),
                    wrong_items=len(getattr(grading_result, "wrong_items", []) or []),
                    questions=len(getattr(grading_result, "questions", []) or []),
                )
            except Exception as e:
                log_event(
                    logger,
                    "grade_llm_failed",
                    level="warning",
                    request_id=req_id,
                    session_id=session_for_ctx,
                    provider=provider_str,
                    error_type=e.__class__.__name__,
                    error=str(e),
                )
                if provider_str == "ark":
                    g0 = time.monotonic()
                    log_event(
                        logger,
                        "grade_llm_fallback_start",
                        level="warning",
                        request_id=req_id,
                        session_id=session_for_ctx,
                        provider="silicon",
                    )
                    grading_result = await _grade_math("silicon")
                    timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                    meta_base["llm_provider_used"] = "silicon"
                    meta_base["llm_used_fallback"] = True
                    log_event(
                        logger,
                        "grade_llm_fallback_done",
                        request_id=req_id,
                        session_id=session_for_ctx,
                        provider="silicon",
                        llm_ms=timings_ms.get("llm_ms"),
                    )
                    grading_result.warnings = (grading_result.warnings or []) + [
                        f"Ark grading error, fell back to qwen3: {str(e)}"
                    ]
                else:
                    raise

            if provider_str == "ark" and _needs_fallback(grading_result):
                ark_summary = grading_result.summary
                ark_warnings = grading_result.warnings or []
                log_event(
                    logger,
                    "grade_llm_fallback_forced",
                    level="warning",
                    request_id=req_id,
                    session_id=session_for_ctx,
                    reason="needs_fallback",
                    ark_summary=ark_summary,
                )
                g0 = time.monotonic()
                grading_result = await _grade_math("silicon")
                timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                meta_base["llm_provider_used"] = "silicon"
                meta_base["llm_used_fallback"] = True
                grading_result.warnings = (grading_result.warnings or []) + [
                    f"Ark grading unavailable, fell back to qwen3. Ark summary: {ark_summary}"
                ] + ark_warnings

            grading_result.wrong_items = sanitize_wrong_items(grading_result.wrong_items)

            # Canonicalize wrong_items from the full question list whenever available.
            # This guarantees stable question_number routing for chat/UI (even if the model forgot to fill it in wrong_items).
            questions_list = getattr(grading_result, "questions", None) or []
            if isinstance(questions_list, list) and questions_list:
                grading_result.wrong_items = derive_wrong_items_from_questions(questions_list)
            else:
                # If wrong_items miss schema-required fields, derive from questions (best-effort fallback).
                wrong_items_invalid = (
                    not grading_result.wrong_items
                    or any(
                        (not isinstance(it, dict))
                        or (not isinstance(it.get("reason"), str))
                        or (not it.get("reason"))
                        for it in grading_result.wrong_items
                    )
                )
                if wrong_items_invalid:
                    grading_result.wrong_items = derive_wrong_items_from_questions(
                        getattr(grading_result, "questions", None) or []
                    )
            grading_result.wrong_items = dedupe_wrong_items(grading_result.wrong_items)
            grading_result.wrong_items = assign_stable_item_ids(grading_result.wrong_items)
            grading_result.wrong_items = sanitize_wrong_items(grading_result.wrong_items)

        elif req.subject == Subject.ENGLISH:
            async def _grade_english(provider: str):
                b = min(float(settings.grade_llm_timeout_seconds), remaining_seconds())
                if b <= 0:
                    raise asyncio.TimeoutError(
                        f"grade SLA exceeded before LLM started (elapsed={int(time.monotonic()-started)}s)"
                    )
                return await _call_blocking_in_thread(
                    llm_client.grade_english,
                    text_content=vision_result.text,
                    mode=req.mode or SimilarityMode.NORMAL,
                    provider=provider,
                    timeout_seconds=b,
                    semaphore=LLM_SEMAPHORE,
                )

            try:
                g0 = time.monotonic()
                grading_result = await _grade_english(provider_str)
                timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                meta_base["llm_provider_used"] = provider_str
            except Exception as e:
                if provider_str == "ark":
                    g0 = time.monotonic()
                    grading_result = await _grade_english("silicon")
                    timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                    meta_base["llm_provider_used"] = "silicon"
                    meta_base["llm_used_fallback"] = True
                    grading_result.warnings = (grading_result.warnings or []) + [
                        f"Ark grading error, fell back to qwen3: {str(e)}"
                    ]
                else:
                    raise

            if provider_str == "ark" and _needs_fallback(grading_result):
                ark_summary = grading_result.summary
                ark_warnings = grading_result.warnings or []
                g0 = time.monotonic()
                grading_result = await _grade_english("silicon")
                timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                meta_base["llm_provider_used"] = "silicon"
                meta_base["llm_used_fallback"] = True
                grading_result.warnings = (grading_result.warnings or []) + [
                    f"Ark grading unavailable, fell back to qwen3. Ark summary: {ark_summary}"
                ] + ark_warnings
            grading_result.wrong_items = sanitize_wrong_items(grading_result.wrong_items)
            questions_list = getattr(grading_result, "questions", None) or []
            if isinstance(questions_list, list) and questions_list:
                grading_result.wrong_items = derive_wrong_items_from_questions(questions_list)
            else:
                wrong_items_invalid = (
                    not grading_result.wrong_items
                    or any(
                        (not isinstance(it, dict))
                        or (not isinstance(it.get("reason"), str))
                        or (not it.get("reason"))
                        for it in grading_result.wrong_items
                    )
                )
                if wrong_items_invalid:
                    grading_result.wrong_items = derive_wrong_items_from_questions(
                        getattr(grading_result, "questions", None) or []
                    )
            grading_result.wrong_items = dedupe_wrong_items(grading_result.wrong_items)
            grading_result.wrong_items = assign_stable_item_ids(grading_result.wrong_items)
            grading_result.wrong_items = sanitize_wrong_items(grading_result.wrong_items)

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported subject: {req.subject}",
            )

    except asyncio.TimeoutError as e:
        # Save vision-only qbank so /chat can still route by question number.
        if session_for_ctx:
            page_urls = [img.url for img in req.images if getattr(img, "url", None)]
            persist_question_bank(
                session_id=session_for_ctx,
                bank=_merge_bank_meta(
                    build_question_bank_from_vision_raw_text(
                    session_id=session_for_ctx,
                    subject=req.subject,
                    vision_raw_text=vision_result.text,
                    page_image_urls=[str(u) for u in page_urls if u],
                ),
                    meta_base,
                ),
                grade_status="failed",
                grade_summary="LLM grading timeout",
                grade_warnings=[f"LLM timeout: {str(e)}"],
                timings_ms=timings_ms,
            )
        return GradeResponse(
            wrong_items=[],
            summary="LLM grading timeout",
            subject=req.subject,
            job_id=None,
            session_id=session_for_ctx,
            status="failed",
            total_items=None,
            wrong_count=None,
            cross_subject_flag=None,
            warnings=[f"LLM timeout: {str(e)}"],
            vision_raw_text=vision_result.text,
        )
    except Exception as e:
        if session_for_ctx:
            page_urls = [img.url for img in req.images if getattr(img, "url", None)]
            persist_question_bank(
                session_id=session_for_ctx,
                bank=_merge_bank_meta(
                    build_question_bank_from_vision_raw_text(
                    session_id=session_for_ctx,
                    subject=req.subject,
                    vision_raw_text=vision_result.text,
                    page_image_urls=[str(u) for u in page_urls if u],
                ),
                    meta_base,
                ),
                grade_status="failed",
                grade_summary=f"LLM grading failed: {str(e)}",
                grade_warnings=[f"LLM error: {str(e)}"],
                timings_ms=timings_ms,
            )
        return GradeResponse(
            wrong_items=[],
            summary=f"LLM grading failed: {str(e)}",
            subject=req.subject,
            job_id=None,
            session_id=session_for_ctx,
            status="failed",
            total_items=None,
            wrong_count=None,
            cross_subject_flag=None,
            warnings=[f"LLM error: {str(e)}"],
            vision_raw_text=vision_result.text,
        )

    # If parsing still failed after fallbacks, treat grading as failed (avoid "done but empty").
    if _needs_fallback(grading_result):
        if session_for_ctx:
            page_urls = [img.url for img in req.images if getattr(img, "url", None)]
            persist_question_bank(
                session_id=session_for_ctx,
                bank=_merge_bank_meta(
                    build_question_bank_from_vision_raw_text(
                    session_id=session_for_ctx,
                    subject=req.subject,
                    vision_raw_text=vision_result.text,
                    page_image_urls=[str(u) for u in page_urls if u],
                ),
                    meta_base,
                ),
                grade_status="failed",
                grade_summary=(getattr(grading_result, "summary", "") or "批改失败").strip(),
                grade_warnings=(getattr(grading_result, "warnings", None) or [])
                + ([vision_fallback_warning] if vision_fallback_warning else []),
                timings_ms=timings_ms,
            )
        return GradeResponse(
            wrong_items=sanitize_wrong_items(getattr(grading_result, "wrong_items", []) or []),
            summary=(getattr(grading_result, "summary", "") or "批改失败").strip(),
            subject=req.subject,
            job_id=None,
            session_id=session_for_ctx,
            status="failed",
            total_items=getattr(grading_result, "total_items", None),
            wrong_count=getattr(grading_result, "wrong_count", None),
            cross_subject_flag=getattr(grading_result, "cross_subject_flag", None),
            warnings=(getattr(grading_result, "warnings", None) or []) + ([vision_fallback_warning] if vision_fallback_warning else []),
            vision_raw_text=vision_result.text,
        )

    # Persist question bank snapshot (full question list) for chat routing.
    if session_for_ctx:
        page_urls = [img.url for img in req.images if getattr(img, "url", None)]
        questions = getattr(grading_result, "questions", None) or []
        if isinstance(questions, list) and questions:
            bank = build_question_bank(
                session_id=session_for_ctx,
                subject=req.subject,
                questions=questions,
                vision_raw_text=vision_result.text,
                page_image_urls=page_urls,
            )
            persist_question_bank(
                session_id=session_for_ctx,
                bank=_merge_bank_meta(bank, meta_base),
                grade_status="done",
                grade_summary=(getattr(grading_result, "summary", "") or "").strip(),
                grade_warnings=(getattr(grading_result, "warnings", None) or [])
                + ([vision_fallback_warning] if vision_fallback_warning else []),
                timings_ms=timings_ms,
            )

    # Defensive: if LLM didn't output counts, compute from normalized results.
    if getattr(grading_result, "wrong_count", None) is None:
        try:
            grading_result.wrong_count = len(getattr(grading_result, "wrong_items", []) or [])
        except Exception:
            grading_result.wrong_count = None
    if getattr(grading_result, "total_items", None) is None:
        try:
            qs = getattr(grading_result, "questions", None) or []
            grading_result.total_items = len(qs) if isinstance(qs, list) and qs else None
        except Exception:
            grading_result.total_items = None

    log_event(
        logger,
        "grade_done",
        request_id=req_id,
        session_id=session_for_ctx,
        status="done",
        vision_provider=meta_base.get("vision_provider_used"),
        llm_provider=meta_base.get("llm_provider_used"),
        llm_used_fallback=meta_base.get("llm_used_fallback"),
        timings_ms=timings_ms,
        wrong_count=getattr(grading_result, "wrong_count", None),
        total_items=getattr(grading_result, "total_items", None),
    )
    return GradeResponse(
        wrong_items=grading_result.wrong_items,
        summary=grading_result.summary,
        subject=req.subject,
        job_id=None,
        session_id=session_for_ctx,
        status="done",
        total_items=grading_result.total_items,
        wrong_count=grading_result.wrong_count,
        cross_subject_flag=grading_result.cross_subject_flag,
        warnings=((grading_result.warnings or []) + ([vision_fallback_warning] if vision_fallback_warning else [])),
        vision_raw_text=vision_result.text,
    )


async def background_grade(job_id: str, req: GradeRequest, provider_str: str):
    """后台执行批改，更新 job_cache。"""
    try:
        result = await perform_grading(req, provider_str)
        cache_store.set(
            f"job:{job_id}",
            {
                "status": "done",
                "created_at": datetime.now().isoformat(),
                "request": req.model_dump(),
                "result": result.model_dump(),
                "finished_at": datetime.now().isoformat(),
            },
            ttl_seconds=IDP_TTL_HOURS * 3600,
        )
    except Exception as e:
        cache_store.set(
            f"job:{job_id}",
            {
                "status": "failed",
                "created_at": datetime.now().isoformat(),
                "request": req.model_dump(),
                "result": None,
                "error": str(e),
                "finished_at": datetime.now().isoformat(),
            },
            ttl_seconds=IDP_TTL_HOURS * 3600,
        )


def background_build_question_index(session_id: str, page_urls: List[str]) -> None:
    """Best-effort background job: build bbox/slice index and store in cache."""
    try:
        index = _build_question_index_for_pages(page_urls)
        save_question_index(session_id, index)
    except Exception as e:
        save_question_index(session_id, {"questions": {}, "warnings": [f"question index build failed: {str(e)}"]})


def validate_images(images: List[Any], provider: VisionProvider):
    """Early validation of image inputs to fail fast."""
    for idx, img in enumerate(images):
        if img.url:
            url_str = str(img.url)
            if not (url_str.startswith("http://") or url_str.startswith("https://")):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: URL must be HTTP/HTTPS"
                )
            if "localhost" in url_str or "127.0.0.1" in url_str:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: URL must be public (no localhost/127)"
                )
        elif img.base64:
            if provider == VisionProvider.DOUBAO:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: Doubao provider only accepts URLs, not Base64"
                )
            # Estimate size: len * 0.75
            est_size = len(img.base64) * 0.75
            if est_size > 20 * 1024 * 1024:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: Base64 image too large (>20MB), please use URL"
                )


@router.post("/grade", response_model=GradeResponse, status_code=status.HTTP_200_OK)
async def grade_homework(
    req: GradeRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """
    批改作业 API (Stub)
    """
    # 1. Early Validation（公共 URL/20MB/Doubao+base64 等）
    validate_images(req.images, req.vision_provider)

    request_id = get_request_id_from_headers(request.headers) or f"req_{uuid.uuid4().hex[:12]}"
    try:
        setattr(req, "_request_id", request_id)
    except Exception:
        pass
    log_event(
        logger,
        "grade_request",
        request_id=request_id,
        session_id=req.session_id or req.batch_id,
        subject=getattr(req.subject, "value", str(req.subject)),
        images=len(req.images or []),
        vision_provider=getattr(req.vision_provider, "value", str(req.vision_provider)),
        has_idempotency=bool(x_idempotency_key),
    )

    # 2. 幂等性校验
    idempotency_key = get_idempotency_key(None, x_idempotency_key)
    if idempotency_key:
        cached_response = check_idempotency(idempotency_key)
        if cached_response:
            log_event(logger, "grade_idempotency_hit", request_id=request_id, idempotency_key=idempotency_key)
            return cached_response

    # 2.5 Ensure session_id is always present so results can be delivered to /chat
    session_for_ctx = _ensure_session_id(req.session_id or req.batch_id)
    req = req.model_copy(update={"session_id": session_for_ctx})

    # 3. 决定同步/异步
    is_large_batch = len(req.images) > 5
    provider_str = "silicon" if req.vision_provider == VisionProvider.QWEN3 else "ark"

    if is_large_batch:
        job_id = generate_job_id()
        cache_store.set(
            f"job:{job_id}",
            {
                "status": "processing",
                "created_at": datetime.now().isoformat(),
                "request": req.model_dump(),
                "result": None,
            },
            ttl_seconds=IDP_TTL_HOURS * 3600,
        )
        background_tasks.add_task(background_grade, job_id, req, provider_str)
        log_event(
            logger,
            "grade_async_enqueued",
            request_id=request_id,
            session_id=session_for_ctx,
            job_id=job_id,
            images=len(req.images or []),
        )
        return GradeResponse(
            wrong_items=[],
            summary="任务已创建，正在处理中...",
            subject=req.subject,
            job_id=job_id,
            session_id=session_for_ctx,
            status="processing",
            total_items=None,
            wrong_count=None,
            cross_subject_flag=None,
            warnings=["大批量任务已转为异步处理"],
            vision_raw_text=None,
        )

    try:
        response = await perform_grading(req, provider_str)
        if session_for_ctx:
            wrong_items_payload: List[Dict[str, Any]] = []
            for item in response.wrong_items or []:
                if hasattr(item, "model_dump"):
                    wrong_items_payload.append(item.model_dump())
                elif isinstance(item, dict):
                    wrong_items_payload.append(item)
                else:
                    # last resort: attempt dict() conversion
                    try:
                        wrong_items_payload.append(dict(item))
                    except Exception:
                        continue
            save_mistakes(session_for_ctx, wrong_items_payload)
            # QIndex: enqueue bbox/slice indexing job to external worker (Redis required)
            page_urls = [img.url for img in req.images if getattr(img, "url", None)]
            if page_urls:
                enqueued = enqueue_qindex_job(session_for_ctx, [str(u) for u in page_urls if u])
                if enqueued:
                    save_question_index(session_for_ctx, {"questions": {}, "warnings": ["qindex queued"]})
                else:
                    save_question_index(session_for_ctx, {"questions": {}, "warnings": ["qindex queue unavailable; skipped"]})
        if idempotency_key:
            cache_response(idempotency_key, response)
        return response
    except HTTPException:
        raise
    except Exception as e:
        log_event(
            logger,
            "grade_failed",
            level="error",
            request_id=request_id,
            session_id=session_for_ctx,
            error_type=e.__class__.__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
