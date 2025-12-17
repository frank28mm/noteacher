from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status

from homework_agent.models.schemas import GradeRequest, GradeResponse, VisionProvider, Subject, SimilarityMode, ImageRef
from homework_agent.services.llm import LLMClient
from homework_agent.services.vision import VisionClient
from homework_agent.core.qbank import (
    assign_stable_item_ids,
    dedupe_wrong_items,
    derive_wrong_items_from_questions,
    sanitize_wrong_items,
)
from homework_agent.utils.url_image_helpers import (
    _download_as_data_uri,
    _first_public_image_url,
    _is_provider_image_fetch_issue,
    _normalize_public_url,
    _probe_url_head,
)
from homework_agent.utils.supabase_image_proxy import _create_proxy_image_urls

# Keep abort type in grade.py to avoid exception-type mismatch across modules.
from homework_agent.api.grade import _GradingAbort, _remaining_seconds  # noqa: E402

logger = logging.getLogger(__name__)


async def _run_grading_vision_stage(
    *,
    req: GradeRequest,
    session_id: str,
    request_id: Optional[str],
    settings: Any,
    started_m: float,
    deadline_m: float,
    vision_prompt: str,
    vision_client: VisionClient,
    page_image_urls: List[str],
    page_image_urls_original: List[str],
    meta_base: Dict[str, Any],
    timings_ms: Dict[str, int],
    call_blocking_in_thread,
    vision_semaphore: asyncio.Semaphore,
    persist_question_bank,
    merge_bank_meta,
    save_grade_progress,
    log_event,
) -> Tuple[Any, List[str], Optional[str]]:
    """
    Vision stage for /grade:
    - runs the primary vision provider
    - handles doubao URL-fetch flakiness (proxy url + base64/data-url retry)
    - (optional) qwen3 fallback is handled by the current vision client configuration
    Returns (vision_result, possibly-updated page_image_urls, vision_fallback_warning).
    May raise _GradingAbort to return a deterministic GradeResponse early.
    """

    def _vision_err_str(err: Exception, budget: float) -> str:
        if isinstance(err, asyncio.TimeoutError):
            return f"timeout after {int(budget)}s"
        s = str(err).strip()
        return s or err.__class__.__name__

    async def _run_vision(provider: VisionProvider, budget: float):
        if budget <= 0:
            raise asyncio.TimeoutError(
                f"grade SLA exceeded before vision started (elapsed={int(time.monotonic()-started_m)}s)"
            )
        return await call_blocking_in_thread(
            vision_client.analyze,
            images=req.images,
            prompt=vision_prompt,
            provider=provider,
            timeout_seconds=budget,
            semaphore=vision_semaphore,
        )

    vision_fallback_warning: Optional[str] = None
    v_budget = min(float(settings.grade_vision_timeout_seconds), _remaining_seconds(deadline_m))
    log_event(
        logger,
        "grade_vision_budget",
        request_id=request_id,
        session_id=session_id,
        provider_requested=getattr(req.vision_provider, "value", str(req.vision_provider)),
        budget_s=v_budget,
        deadline_s=max(0, int(deadline_m - started_m)),
        images=len(req.images or []),
    )
    if v_budget <= 0:
        persist_question_bank(
            session_id=session_id,
            bank=merge_bank_meta(
                {
                    "session_id": session_id,
                    "subject": req.subject.value if hasattr(req.subject, "value") else str(req.subject),
                    "vision_raw_text": None,
                    "page_image_urls": [
                        v
                        for img in (req.images or [])
                        for v in [_normalize_public_url(getattr(img, "url", None))]
                        if v
                    ],
                    "questions": {},
                },
                meta_base,
            ),
            grade_status="failed",
            grade_summary="Vision analysis not available",
            grade_warnings=["grade SLA exceeded before vision started"],
            timings_ms=timings_ms,
        )
        raise _GradingAbort(
            GradeResponse(
                wrong_items=[],
                summary="Vision analysis not available",
                subject=req.subject,
                job_id=None,
                session_id=session_id,
                status="failed",
                total_items=None,
                wrong_count=None,
                cross_subject_flag=None,
                warnings=["grade SLA exceeded before vision started"],
                vision_raw_text=None,
            )
        )

    try:
        log_event(
            logger,
            "vision_start",
            request_id=request_id,
            session_id=session_id,
            provider=getattr(req.vision_provider, "value", str(req.vision_provider)),
            budget_s=v_budget,
        )
        save_grade_progress(
            session_id,
            "vision_start",
            f"Vision 识别中（{getattr(req.vision_provider, 'value', str(req.vision_provider))}）…",
            {"budget_s": v_budget},
        )
        v0 = time.monotonic()
        vision_result = await _run_vision(req.vision_provider, v_budget)
        timings_ms["vision_ms"] = int((time.monotonic() - v0) * 1000)
        meta_base["vision_provider_used"] = getattr(req.vision_provider, "value", str(req.vision_provider))
        log_event(
            logger,
            "vision_done",
            request_id=request_id,
            session_id=session_id,
            provider=meta_base.get("vision_provider_used"),
            vision_ms=timings_ms.get("vision_ms"),
            vision_text_len=len(getattr(vision_result, "text", "") or ""),
        )
        save_grade_progress(
            session_id,
            "vision_done",
            f"Vision 识别完成（{meta_base.get('vision_provider_used')}）",
            {
                "vision_ms": timings_ms.get("vision_ms"),
                "vision_text_len": len(getattr(vision_result, "text", "") or ""),
            },
        )
        return vision_result, page_image_urls, vision_fallback_warning
    except Exception as e:
        log_event(
            logger,
            "vision_failed",
            level="warning",
            request_id=request_id,
            session_id=session_id,
            provider=getattr(req.vision_provider, "value", str(req.vision_provider)),
            error_type=e.__class__.__name__,
            error=str(e),
            budget_s=v_budget,
        )
        save_grade_progress(
            session_id,
            "vision_failed",
            f"Vision 识别失败（{getattr(req.vision_provider, 'value', str(req.vision_provider))}）：{_vision_err_str(e, v_budget)}",
        )

        # Keep the original behavior: only doubao triggers robust retry paths.
        if req.vision_provider != VisionProvider.DOUBAO:
            persist_question_bank(
                session_id=session_id,
                bank=merge_bank_meta(
                    {
                        "session_id": session_id,
                        "subject": req.subject.value if hasattr(req.subject, "value") else str(req.subject),
                        "vision_raw_text": None,
                        "page_image_urls": [
                            v
                            for img in (req.images or [])
                            for v in [_normalize_public_url(getattr(img, "url", None))]
                            if v
                        ],
                        "questions": {},
                    },
                    meta_base,
                ),
                grade_status="failed",
                grade_summary="Vision analysis not available",
                grade_warnings=[f"Vision analysis failed: {_vision_err_str(e, v_budget)}"],
                timings_ms=timings_ms,
            )
            raise _GradingAbort(
                GradeResponse(
                    wrong_items=[],
                    summary="Vision analysis not available",
                    subject=req.subject,
                    job_id=None,
                    session_id=session_id,
                    status="failed",
                    total_items=None,
                    wrong_count=None,
                    cross_subject_flag=None,
                    warnings=[f"Vision analysis failed: {_vision_err_str(e, v_budget)}"],
                    vision_raw_text=None,
                )
            )

        probe = _probe_url_head(_first_public_image_url(req.images))
        v_budget2 = min(float(settings.grade_vision_timeout_seconds), _remaining_seconds(deadline_m))
        if v_budget2 <= 0:
            persist_question_bank(
                session_id=session_id,
                bank=merge_bank_meta(
                    {
                        "session_id": session_id,
                        "subject": req.subject.value if hasattr(req.subject, "value") else str(req.subject),
                        "vision_raw_text": None,
                        "page_image_urls": [
                            v
                            for img in (req.images or [])
                            for v in [_normalize_public_url(getattr(img, "url", None))]
                            if v
                        ],
                        "questions": {},
                    },
                    meta_base,
                ),
                grade_status="failed",
                grade_summary="Vision analysis not available",
                grade_warnings=[
                    w
                    for w in [
                        f"Vision(doubao) failed: {_vision_err_str(e, v_budget)}",
                        probe,
                        "grade SLA exceeded before vision fallback",
                    ]
                    if w
                ],
                timings_ms=timings_ms,
            )
            raise _GradingAbort(
                GradeResponse(
                    wrong_items=[],
                    summary="Vision analysis not available",
                    subject=req.subject,
                    job_id=None,
                    session_id=session_id,
                    status="failed",
                    total_items=None,
                    wrong_count=None,
                    cross_subject_flag=None,
                    warnings=[
                        w
                        for w in [
                            f"Vision(doubao) failed: {_vision_err_str(e, v_budget)}",
                            probe,
                            "grade SLA exceeded before vision fallback",
                        ]
                        if w
                    ],
                    vision_raw_text=None,
                )
            )

        # 0) If provider-side image_url fetch is flaky, create a lightweight proxy URL and retry.
        proxy_retry_succeeded = False
        if _is_provider_image_fetch_issue(e) and page_image_urls:
            save_grade_progress(
                session_id,
                "vision_proxy_start",
                "生成轻量图片副本（降低拉取失败）…",
                None,
            )
            proxy_urls = _create_proxy_image_urls(page_image_urls, session_id=session_id, prefix="proxy/")
            if proxy_urls:
                page_image_urls = proxy_urls
                meta_base["page_image_urls_original"] = page_image_urls_original
                meta_base["page_image_urls_proxy"] = proxy_urls

                save_grade_progress(
                    session_id,
                    "vision_retry_start",
                    "Vision 识别重试（doubao：使用轻量副本 URL）…",
                    {"budget_s": v_budget2},
                )
                v_retry0 = time.monotonic()
                vision_result = await call_blocking_in_thread(
                    vision_client.analyze,
                    images=[ImageRef(url=u) for u in proxy_urls],
                    prompt=vision_prompt,
                    provider=VisionProvider.DOUBAO,
                    timeout_seconds=v_budget2,
                    semaphore=vision_semaphore,
                )
                timings_ms["vision_ms"] = int((time.monotonic() - v_retry0) * 1000)
                meta_base["vision_provider_used"] = VisionProvider.DOUBAO.value
                meta_base["vision_used_proxy_url"] = True
                proxy_retry_succeeded = True
                log_event(
                    logger,
                    "vision_retry_done",
                    request_id=request_id,
                    session_id=session_id,
                    provider=meta_base.get("vision_provider_used"),
                    used_proxy_url=True,
                    vision_text_len=len(getattr(vision_result, "text", "") or ""),
                )
                save_grade_progress(
                    session_id,
                    "vision_done",
                    "Vision 识别完成（doubao：轻量副本 URL 兜底）",
                    {"used_proxy_url": True, "vision_text_len": len(getattr(vision_result, "text", "") or "")},
                )
                vision_fallback_warning = (
                    f"Vision(doubao) URL 拉取失败，已生成轻量副本 URL 兜底：{_vision_err_str(e, v_budget)}"
                    + (f"；{probe}" if probe else "")
                )
                return vision_result, page_image_urls, vision_fallback_warning

        # 1) doubao retry with local base64 (data-url) if we can convert at least one url
        if not proxy_retry_succeeded:
            save_grade_progress(
                session_id,
                "vision_retry_start",
                "Vision 识别重试（doubao：本地下载+base64）…",
                {"budget_s": v_budget2},
            )
            converted_images: List[Any] = []
            converted_any = False
            for u in page_image_urls or page_image_urls_original:
                data_uri = _download_as_data_uri(u)
                if data_uri:
                    converted_any = True
                    converted_images.append(ImageRef(base64=data_uri))
                else:
                    converted_images.append(ImageRef(url=u))
            if converted_any:
                meta_base["vision_used_base64_fallback"] = True
            v_retry0 = time.monotonic()
            vision_result = await call_blocking_in_thread(
                vision_client.analyze,
                images=converted_images,
                prompt=vision_prompt,
                provider=VisionProvider.DOUBAO,
                timeout_seconds=v_budget2,
                semaphore=vision_semaphore,
            )
            timings_ms["vision_ms"] = int((time.monotonic() - v_retry0) * 1000)
            meta_base["vision_provider_used"] = VisionProvider.DOUBAO.value
            meta_base["vision_used_base64_fallback"] = converted_any
            log_event(
                logger,
                "vision_retry_done",
                request_id=request_id,
                session_id=session_id,
                provider=meta_base.get("vision_provider_used"),
                used_base64_fallback=converted_any,
                vision_text_len=len(getattr(vision_result, "text", "") or ""),
            )
            save_grade_progress(
                session_id,
                "vision_done",
                "Vision 识别完成（doubao：base64 兜底）",
                {"used_base64_fallback": converted_any, "vision_text_len": len(getattr(vision_result, "text", "") or "")},
            )
            if converted_any:
                vision_fallback_warning = (
                    f"Vision(doubao) URL 拉取失败，已用 base64 兜底：{_vision_err_str(e, v_budget)}"
                    + (f"；{probe}" if probe else "")
                )
            return vision_result, page_image_urls, vision_fallback_warning


async def _run_grading_llm_stage(
    *,
    req: GradeRequest,
    provider_str: str,
    llm_client: LLMClient,
    vision_text: str,
    settings: Any,
    started_m: float,
    deadline_m: float,
    session_id: str,
    request_id: Optional[str],
    meta_base: Dict[str, Any],
    timings_ms: Dict[str, int],
    call_blocking_in_thread,
    llm_semaphore: asyncio.Semaphore,
    save_grade_progress,
    log_event,
) -> Any:
    """LLM grading stage for /grade (includes Ark->Qwen3 fallback on errors or low-quality outputs)."""

    if req.subject == Subject.MATH:

        async def _grade_math(provider: str):
            b = min(float(settings.grade_llm_timeout_seconds), _remaining_seconds(deadline_m))
            if b <= 0:
                raise asyncio.TimeoutError(
                    f"grade SLA exceeded before LLM started (elapsed={int(time.monotonic()-started_m)}s)"
                )
            return await call_blocking_in_thread(
                llm_client.grade_math,
                text_content=vision_text,
                provider=provider,
                timeout_seconds=b,
                semaphore=llm_semaphore,
            )

        log_event(logger, "grade_llm_start", request_id=request_id, session_id=session_id, provider=provider_str)
        save_grade_progress(session_id, "llm_start", "批改中（LLM 推理中）…", {"provider": provider_str})
        try:
            g0 = time.monotonic()
            grading_result = await _grade_math(provider_str)
            timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
            meta_base["llm_provider_used"] = provider_str
        except Exception as e:
            log_event(
                logger,
                "grade_llm_failed",
                level="warning",
                request_id=request_id,
                session_id=session_id,
                provider=provider_str,
                error_type=e.__class__.__name__,
                error=str(e),
            )
            save_grade_progress(session_id, "llm_failed", f"批改失败：{e.__class__.__name__}: {str(e)}", None)
            if provider_str == "ark":
                g0 = time.monotonic()
                grading_result = await _grade_math("silicon")
                timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                meta_base["llm_provider_used"] = "silicon"
                meta_base["llm_used_fallback"] = True
                save_grade_progress(
                    session_id,
                    "llm_done",
                    "批改完成（qwen3 兜底）",
                    {"provider": "silicon", "llm_ms": timings_ms.get("llm_ms")},
                )
                grading_result.warnings = (grading_result.warnings or []) + [
                    f"Ark grading error, fell back to qwen3: {str(e)}"
                ]
            else:
                raise
        log_event(
            logger,
            "grade_llm_done",
            request_id=request_id,
            session_id=session_id,
            provider=meta_base.get("llm_provider_used"),
            llm_ms=timings_ms.get("llm_ms"),
            wrong_items=len(getattr(grading_result, "wrong_items", []) or []),
            questions=len(getattr(grading_result, "questions", []) or []),
        )
        save_grade_progress(
            session_id,
            "llm_done",
            "批改完成（LLM 推理结束）",
            {
                "provider": meta_base.get("llm_provider_used"),
                "llm_ms": timings_ms.get("llm_ms"),
                "questions": len(getattr(grading_result, "questions", []) or []),
            },
        )

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
        return grading_result

    if req.subject == Subject.ENGLISH:

        async def _grade_english(provider: str):
            b = min(float(settings.grade_llm_timeout_seconds), _remaining_seconds(deadline_m))
            if b <= 0:
                raise asyncio.TimeoutError(
                    f"grade SLA exceeded before LLM started (elapsed={int(time.monotonic()-started_m)}s)"
                )
            return await call_blocking_in_thread(
                llm_client.grade_english,
                text_content=vision_text,
                mode=req.mode or SimilarityMode.NORMAL,
                provider=provider,
                timeout_seconds=b,
                semaphore=llm_semaphore,
            )

        log_event(logger, "grade_llm_start", request_id=request_id, session_id=session_id, provider=provider_str)
        save_grade_progress(session_id, "llm_start", "批改中（LLM 推理中）…", {"provider": provider_str})
        try:
            g0 = time.monotonic()
            grading_result = await _grade_english(provider_str)
            timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
            meta_base["llm_provider_used"] = provider_str
        except Exception as e:
            log_event(
                logger,
                "grade_llm_failed",
                level="warning",
                request_id=request_id,
                session_id=session_id,
                provider=provider_str,
                error_type=e.__class__.__name__,
                error=str(e),
            )
            save_grade_progress(session_id, "llm_failed", f"批改失败：{e.__class__.__name__}: {str(e)}", None)
            if provider_str == "ark":
                g0 = time.monotonic()
                grading_result = await _grade_english("silicon")
                timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                meta_base["llm_provider_used"] = "silicon"
                meta_base["llm_used_fallback"] = True
                save_grade_progress(
                    session_id,
                    "llm_done",
                    "批改完成（qwen3 兜底）",
                    {"provider": "silicon", "llm_ms": timings_ms.get("llm_ms")},
                )
                grading_result.warnings = (grading_result.warnings or []) + [
                    f"Ark grading error, fell back to qwen3: {str(e)}"
                ]
            else:
                raise
        save_grade_progress(
            session_id,
            "llm_done",
            "批改完成（LLM 推理结束）",
            {"provider": meta_base.get("llm_provider_used"), "llm_ms": timings_ms.get("llm_ms")},
        )

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
        return grading_result

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported subject: {req.subject}")
