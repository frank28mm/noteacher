from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from homework_agent.core.qbank import _normalize_question_number
from homework_agent.core.slice_policy import (
    analyze_visual_risk,
    pick_question_numbers_for_slices,
    should_create_slices_for_bank,
)
from homework_agent.models.schemas import ChatRequest, ChatResponse
from homework_agent.services.llm import LLMClient
from homework_agent.api.session import (
    get_question_bank,
    get_question_index,
    save_qindex_placeholder,
    save_question_bank,
    save_question_index,
    save_session,
    _now_ts,
)
from homework_agent.utils.observability import log_event, trace_span
from homework_agent.utils.settings import get_settings
from homework_agent.utils.submission_store import (
    load_qindex_image_refs,
    resolve_submission_for_session,
)

# Keep abort type + small helpers in chat.py (avoid exception-type mismatch across modules).
from homework_agent.api.chat import (  # noqa: E402
    _abort_with_assistant_message,
    _extract_requested_question_number,
    _format_math_for_display,
    _has_explicit_question_switch_intent,
    _qindex_has_slices_for_question,
    _select_question_number_from_text,
    _user_requests_visual_check,
)

import homework_agent.api.chat as chat_api  # noqa: E402

logger = logging.getLogger(__name__)

def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_qindex_refs_from_db(
    *,
    session_id: str,
    request_id: str,
    fallback_user_id: str,
    question_number: str,
) -> Optional[Dict[str, Any]]:
    """DB fallback: load qindex image refs (within TTL) even if Redis was restarted."""
    try:
        resolved = resolve_submission_for_session(session_id)
        real_user_id = fallback_user_id
        if isinstance(resolved, dict):
            real_user_id = resolved.get("user_id") or fallback_user_id
            log_event(
                logger,
                "chat_resolved_submission_for_session",
                request_id=request_id,
                session_id=session_id,
                resolved_user_id=real_user_id,
                submission_id=resolved.get("submission_id"),
            )

        db_refs = load_qindex_image_refs(
            user_id=real_user_id,
            session_id=session_id,
            question_number=str(question_number),
        )
        if isinstance(db_refs, dict) and db_refs:
            log_event(
                logger,
                "chat_loaded_db_slices",
                request_id=request_id,
                session_id=session_id,
                question_number=str(question_number),
                has_slices=True,
            )
            return db_refs

        log_event(
            logger,
            "chat_no_db_slices_found",
            request_id=request_id,
            session_id=session_id,
            question_number=str(question_number),
            real_user_id=real_user_id,
        )
        return None
    except Exception as e:
        log_event(
            logger,
            "chat_db_load_error",
            request_id=request_id,
            session_id=session_id,
            question_number=str(question_number),
            error_type=e.__class__.__name__,
            error=str(e),
            level="warning",
        )
        return None


def _extract_focus_image_urls(
    *, wrong_item_context: Dict[str, Any]
) -> tuple[Optional[List[str]], Optional[str]]:
    """
    Best-effort: pick a representative image URL for the current focus question to:
    - render in UI (demo: show in chat bubbles)
    - keep UX consistent with what the LLM sees (prefer diagram/figure slices)
    """
    focus_question = wrong_item_context.get("focus_question")
    if not isinstance(focus_question, dict):
        return None, None

    def _pick_from_pages(pages: Any) -> tuple[Optional[str], Optional[str]]:
        if not isinstance(pages, list):
            return None, None
        for p in pages:
            if not isinstance(p, dict):
                continue
            regions = p.get("regions")
            if isinstance(regions, list):
                for r in regions:
                    if not isinstance(r, dict):
                        continue
                    if (r.get("kind") or "").lower() == "figure" and r.get(
                        "slice_image_url"
                    ):
                        return str(r.get("slice_image_url")), "slice_figure"

            slice_urls = p.get("slice_image_urls")
            if isinstance(slice_urls, list) and slice_urls:
                return str(slice_urls[0]), "slice_question"
            slice_url = p.get("slice_image_url")
            if slice_url:
                return str(slice_url), "slice_question"
            if isinstance(regions, list):
                for r in regions:
                    if isinstance(r, dict) and r.get("slice_image_url"):
                        return str(r.get("slice_image_url")), "slice_question"
        return None, None

    image_refs = focus_question.get("image_refs")
    if isinstance(image_refs, dict):
        url, src = _pick_from_pages(image_refs.get("pages"))
        if url:
            return [url], src

    url, src = _pick_from_pages(focus_question.get("pages"))
    if url:
        return [url], src

    page_urls = focus_question.get("page_image_urls")
    if isinstance(page_urls, list) and page_urls:
        return [str(page_urls[0])], "page"
    page_url = focus_question.get("page_image_url")
    if page_url:
        return [str(page_url)], "page"

    return None, None


async def _run_mandatory_visual_path(
    *,
    req: ChatRequest,
    session_id: str,
    request_id: str,
    user_id: str,
    session_data: Dict[str, Any],
    wrong_item_context: Dict[str, Any],
) -> AsyncIterator[bytes]:
    """
    Best-effort: ensure slices are enqueued and cached refs are refreshed.
    No fail-closed behavior (chat must keep responding even if visuals are missing).
    """
    focus_obj = wrong_item_context.get("focus_question")
    fqnum = wrong_item_context.get("focus_question_number")
    if not (isinstance(focus_obj, dict) and fqnum):
        return

    user_visual_hint, _ = analyze_visual_risk(
        subject=req.subject,
        question_content=req.question,
        warnings=None,
    )
    visual_risk = bool(focus_obj.get("visual_risk") is True)
    explicit_visual = bool(_user_requests_visual_check(req.question))
    must_visual = bool(explicit_visual or user_visual_hint or visual_risk)
    if not must_visual:
        return

    # 1) Ensure qindex slices (for focused question)
    qindex_now = get_question_index(session_id) if session_id else None
    ready = isinstance(qindex_now, dict) and _qindex_has_slices_for_question(
        qindex_now, str(fqnum)
    )
    if not ready:
        db_refs = _load_qindex_refs_from_db(
            session_id=session_id,
            request_id=request_id,
            fallback_user_id=user_id,
            question_number=str(fqnum),
        )
        if isinstance(db_refs, dict) and db_refs:
            focus_obj["image_refs"] = db_refs
            ready = True

    if not ready:
        ok, reason = chat_api.qindex_is_configured()
        if not ok:
            save_qindex_placeholder(session_id, f"qindex skipped: {reason}")
        else:
            # Enqueue if not already queued.
            queued_already = False
            if isinstance(qindex_now, dict):
                ws = qindex_now.get("warnings") or []
                if isinstance(ws, list) and any("queued" in str(w) for w in ws):
                    queued_already = True
                if qindex_now.get("questions"):
                    queued_already = True

            qbank_now = get_question_bank(session_id) if session_id else None
            page_urls = (
                (qbank_now or {}).get("page_image_urls")
                if isinstance(qbank_now, dict)
                else None
            )
            allow = (
                pick_question_numbers_for_slices(qbank_now)
                if isinstance(qbank_now, dict)
                else []
            )
            fq = str(fqnum).strip()
            if fq and fq not in allow:
                allow = [*allow, fq] if allow else [fq]

            if (not queued_already) and isinstance(page_urls, list) and page_urls:
                if chat_api.enqueue_qindex_job(
                    session_id,
                    [str(u) for u in page_urls if u],
                    question_numbers=allow,
                    request_id=request_id,
                ):
                    save_question_index(
                        session_id,
                        {"questions": {}, "warnings": ["qindex queued (chat)"]},
                    )
                else:
                    save_qindex_placeholder(
                        session_id, "qindex skipped: redis_unavailable"
                    )

    # 2) Refresh image refs + cached facts into focus_obj
    qindex_now = get_question_index(session_id) if session_id else None
    if isinstance(qindex_now, dict):
        qs = qindex_now.get("questions")
        if isinstance(qs, dict) and str(fqnum) in qs:
            focus_obj["image_refs"] = qs.get(str(fqnum))
        if qindex_now.get("warnings"):
            wrong_item_context["index_warnings"] = qindex_now.get("warnings")

    try:
        qbank_now = get_question_bank(session_id) if session_id else None
        if isinstance(qbank_now, dict):
            qs = qbank_now.get("questions")
            if (
                isinstance(qs, dict)
                and str(fqnum) in qs
                and isinstance(qs.get(str(fqnum)), dict)
            ):
                cached = qs.get(str(fqnum)) or {}
                if isinstance(cached, dict):
                    focus_obj.update({k: v for k, v in cached.items() if v is not None})
                    wrong_item_context["focus_question"] = focus_obj
    except Exception as e:
        logger.debug(f"Refreshing cached visual facts failed: {e}")
    if False:
        yield b""


@trace_span("chat.prepare_context")
def _prepare_chat_context_or_abort(
    *,
    req: ChatRequest,
    session_id: str,
    request_id: str,
    user_id: str,
    session_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Resolve qbank + determine focus question + attach optional image refs.
    Returns wrong_item_context (includes focus question payload).
    May raise _ChatAbort for deterministic early exits.
    """
    # Chat 只能基于 /grade 交付的“题库快照”对话；缺失则直接提示先批改，禁止编造。
    qbank = get_question_bank(session_id) if session_id else None
    if not (
        isinstance(qbank, dict)
        and isinstance(qbank.get("questions"), dict)
        and qbank.get("questions")
    ):
        log_event(
            logger,
            "chat_qbank_missing",
            level="warning",
            request_id=request_id,
            session_id=session_id,
        )
        _abort_with_assistant_message(
            session_id=session_id,
            session_data=session_data,
            message=(
                "我还没有拿到本次作业的“题库快照”（识别原文/判定结果/题目信息）。"
                "请先在【智能批改】里上传照片并完成批改，然后用返回的 session_id 再来辅导。"
            ),
            done_status="error",
        )

    bank_questions = qbank.get("questions")
    bank_questions_str: Dict[str, Any] = {
        str(k): v for k, v in (bank_questions or {}).items()
    }
    available_qnums = sorted(bank_questions_str.keys(), key=len, reverse=True)

    wrong_item_context: Dict[str, Any] = {
        "available_question_numbers": available_qnums[:200],
    }

    # Determine requested question number (explicit) and bind focus deterministically.
    requested_qn = _extract_requested_question_number(req.question)
    requested_qn = _normalize_question_number(requested_qn) if requested_qn else None
    if requested_qn:
        # If user explicitly asked for a question that does not exist, do NOT keep old focus.
        if requested_qn not in bank_questions_str:
            # Allow prefix matching: "28" -> "28(1)②" etc.
            candidates = [
                k
                for k in available_qnums
                if str(k).startswith(f"{requested_qn}(")
                or str(k).startswith(requested_qn)
            ]
            if candidates:
                requested_qn = sorted(candidates, key=len)[0]
            else:
                log_event(
                    logger,
                    "chat_route_not_found",
                    level="warning",
                    request_id=request_id,
                    session_id=session_id,
                    requested_qn=requested_qn,
                    available_count=len(available_qnums),
                )
                _abort_with_assistant_message(
                    session_id=session_id,
                    session_data=session_data,
                    message=(
                        f"我没能在本次批改结果里定位到第{requested_qn}题的题干/选项信息。"
                        + (
                            f" 当前可聊题号：{', '.join(available_qnums[:30])}。"
                            if available_qnums
                            else ""
                        )
                        + " 你可以换一个题号再问，或重新上传更清晰的照片后再批改一次。"
                    ),
                    done_status="continue",
                    question_candidates=available_qnums[:30],
                )
        session_data["focus_question_number"] = str(requested_qn)
    else:
        # Only attempt to switch focus when user explicitly intends to talk about a question.
        # This avoids false-positives from math expressions like "t(t-8)+16".
        explicit_intent = _has_explicit_question_switch_intent(req.question)
        mentioned, match_type = _select_question_number_from_text(
            req.question,
            available_qnums,
            question_meta=bank_questions_str,
            allow_numeric_fallback=explicit_intent,
        )
        if explicit_intent or mentioned:
            log_event(
                logger,
                "question_routing",
                request_id=request_id,
                session_id=session_id,
                user_input=req.question,
                matched_qn=mentioned or "none",
                match_type=match_type,
                explicit_intent=explicit_intent,
                available_qns=available_qnums[:10],
            )
            if mentioned:
                session_data["focus_question_number"] = str(mentioned)
            else:
                wants_switch = any(
                    k in (req.question or "") for k in ("换一题", "下一题", "换个", "换个题")
                )
                if wants_switch or not session_data.get("focus_question_number"):
                    _abort_with_assistant_message(
                        session_id=session_id,
                        session_data=session_data,
                        message=(
                            "这个题目没有找到呢。你可以直接说题号或题名。"
                            + (
                                f" 当前可聊题目：{', '.join(available_qnums[:30])}。"
                                if available_qnums
                                else ""
                            )
                        ),
                        done_status="continue",
                        question_candidates=available_qnums[:30],
                    )
                else:
                    log_event(
                        logger,
                        "chat_focus_retained_on_implicit_intent",
                        request_id=request_id,
                        session_id=session_id,
                        focus_question_number=session_data.get("focus_question_number"),
                        user_input=req.question,
                    )

    focus_q = session_data.get("focus_question_number")
    focus_q = str(focus_q) if focus_q is not None else None
    log_event(
        logger,
        "chat_focus_bound",
        request_id=request_id,
        session_id=session_id,
        focus_question_number=focus_q,
        requested_qn=requested_qn,
    )
    if not (focus_q and focus_q in bank_questions_str):
        # No focus yet: ask user to specify a question number (avoid hallucination).
        _abort_with_assistant_message(
            session_id=session_id,
            session_data=session_data,
            message=(
                "你想先聊哪一题？请直接说“讲第几题”。"
                + (
                    f" 当前可聊题号：{', '.join(available_qnums[:30])}。"
                    if available_qnums
                    else ""
                )
            ),
            done_status="continue",
            question_candidates=available_qnums[:30],
        )

    focus_payload = dict(bank_questions_str.get(focus_q) or {})
    focus_payload["question_number"] = str(focus_q)

    # Add image refs if available (bbox/slice index) - optional enhancement only.
    qindex = get_question_index(session_id) if session_id else None
    if isinstance(qindex, dict):
        qidx_questions = qindex.get("questions")
        if isinstance(qidx_questions, dict) and focus_q in qidx_questions:
            image_refs = qidx_questions.get(focus_q)
            focus_payload["image_refs"] = image_refs
            log_event(
                logger,
                "chat_attaching_image_refs",
                request_id=request_id,
                session_id=session_id,
                focus_question_number=focus_q,
                has_image_refs=bool(image_refs),
                has_pages=bool(
                    image_refs.get("pages") if isinstance(image_refs, dict) else False
                ),
            )
        if qindex.get("warnings"):
            wrong_item_context["index_warnings"] = qindex.get("warnings")
    else:
        log_event(
            logger,
            "chat_no_qindex_found",
            request_id=request_id,
            session_id=session_id,
            focus_question_number=focus_q,
        )

    # Always keep page urls for potential "re-look the page" fallback (geometry etc.)
    page_urls = qbank.get("page_image_urls")
    if isinstance(page_urls, list) and page_urls:
        focus_payload["page_image_urls"] = page_urls

    wrong_item_context["focus_question_number"] = str(focus_q)
    wrong_item_context["focus_question"] = focus_payload

    # Also persist image_refs to qbank for future use (best-effort)
    try:
        qbank_now = get_question_bank(session_id)
        if isinstance(qbank_now, dict):
            qs = qbank_now.get("questions")
            if (
                isinstance(qs, dict)
                and str(focus_q) in qs
                and isinstance(qs.get(str(focus_q)), dict)
            ):
                if "image_refs" in focus_payload:
                    qs[str(focus_q)]["image_refs"] = focus_payload["image_refs"]
                qbank_now["questions"] = qs
                save_question_bank(session_id, qbank_now)
    except Exception as e:
        logger.debug(f"Persisting image_refs to qbank failed (best-effort): {e}")

    try:
        if not requested_qn and not _has_explicit_question_switch_intent(req.question):
            log_event(
                logger,
                "chat_focus_question_maintained",
                request_id=request_id,
                session_id=session_id,
                focus_question_number=session_data.get("focus_question_number"),
            )
    except Exception as e:
        logger.debug(f"Focus question log failed: {e}")

    # Optional optimization: if this session likely contains visual/diagram risks, enqueue qindex slices in background.
    # This is best-effort and must never block chat (user should not be aware of it).
    try:
        qindex_now = get_question_index(session_id) if session_id else None
        queued_already = False
        if isinstance(qindex_now, dict):
            ws = qindex_now.get("warnings") or []
            if isinstance(ws, list) and any("queued" in str(w) for w in ws):
                queued_already = True
            if qindex_now.get("questions"):
                queued_already = True

        focus_obj_for_qindex = wrong_item_context.get("focus_question")
        focus_qn_for_qindex = wrong_item_context.get("focus_question_number")
        user_visual_hint = False
        try:
            user_visual_hint, _ = analyze_visual_risk(
                subject=req.subject,
                question_content=req.question,
                warnings=None,
            )
        except Exception as e:
            logger.debug(f"analyze_visual_risk failed: {e}")
            user_visual_hint = False
        if (
            not queued_already
            and isinstance(focus_obj_for_qindex, dict)
            and (focus_obj_for_qindex.get("visual_risk") is True or user_visual_hint)
        ):
            qbank_now = get_question_bank(session_id) if session_id else None
            if isinstance(qbank_now, dict) and (
                should_create_slices_for_bank(qbank_now) or user_visual_hint
            ):
                page_urls_now = qbank_now.get("page_image_urls")
                if isinstance(page_urls_now, list) and page_urls_now:
                    allow = pick_question_numbers_for_slices(qbank_now)
                    # If user explicitly hints there is a diagram/table/etc, make sure we slice the focused question.
                    if user_visual_hint and focus_qn_for_qindex:
                        fq = str(focus_qn_for_qindex).strip()
                        if fq and fq not in allow:
                            allow = [*allow, fq]
                    if not allow and focus_qn_for_qindex:
                        allow = [str(focus_qn_for_qindex).strip()]

                    ok, reason = chat_api.qindex_is_configured()
                    if not ok:
                        save_qindex_placeholder(session_id, f"qindex skipped: {reason}")
                    else:
                        if chat_api.enqueue_qindex_job(
                            session_id,
                            [str(u) for u in page_urls_now if u],
                            question_numbers=allow,
                            request_id=request_id,
                        ):
                            save_question_index(
                                session_id,
                                {"questions": {}, "warnings": ["qindex queued (chat)"]},
                            )
                            log_event(
                                logger,
                                "chat_qindex_enqueued",
                                request_id=request_id,
                                session_id=session_id,
                            )
                        else:
                            save_qindex_placeholder(
                                session_id, "qindex skipped: redis_unavailable"
                            )
    except Exception as e:
        logger.debug(f"Qindex enqueue failed (best-effort): {e}")

    log_event(
        logger,
        "chat_context_ready",
        request_id=request_id,
        session_id=session_id,
        focus_qn=focus_q,
        has_qindex=bool(get_question_index(session_id)),
    )
    return wrong_item_context


async def _stream_socratic_llm_to_sse(
    *,
    llm_client: LLMClient,
    req: ChatRequest,
    session_id: str,
    session_data: Dict[str, Any],
    wrong_item_context: Dict[str, Any],
    current_turn: int,
    provider_str: str,
    model_override: Optional[str],
    prompt_variant: Optional[str],
    request_id: str,
    started_m: float,
) -> AsyncIterator[bytes]:
    """True streaming: LLM token stream -> SSE chat events (preserves existing behavior)."""
    settings = get_settings()
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    DONE = object()

    # Update session immediately with user's message so LLM can see the conversation history.
    # Avoid duplicating the same user message when we already appended it earlier
    # (e.g. during mandatory "读图/切片" prelude).
    already_has_user = False
    try:
        for m in reversed(session_data.get("history") or []):
            if isinstance(m, dict) and m.get("role") == "user":
                already_has_user = str(m.get("content") or "") == str(req.question)
                break
    except Exception as e:
        logger.debug(f"Checking for duplicate user message failed: {e}")
        already_has_user = False
    if not already_has_user:
        session_data["history"].append({"role": "user", "content": req.question})
    llm_history = list(session_data["history"][-12:])
    summary = session_data.get("summary")
    if isinstance(summary, str) and summary.strip():
        llm_history = [
            {"role": "system", "content": f"会话摘要：{summary.strip()}"}
        ] + llm_history

    def _producer():
        try:
            for chunk in llm_client.socratic_tutor_stream(
                question=req.question,
                wrong_item_context=wrong_item_context,
                session_id=session_id,
                interaction_count=current_turn,
                provider=provider_str,
                model_override=model_override,
                history=llm_history,
                prompt_variant=prompt_variant,
            ):
                asyncio.run_coroutine_threadsafe(q.put(chunk), loop)
            asyncio.run_coroutine_threadsafe(q.put(DONE), loop)
        except Exception as ex:
            logger.error(f"LLM streaming failed: {ex}")
            asyncio.run_coroutine_threadsafe(q.put({"error": str(ex)}), loop)

    llm_stream_started_m = time.monotonic()
    producer_task = asyncio.create_task(asyncio.to_thread(_producer))

    # Add placeholder assistant message for streaming updates
    assistant_msg = {"role": "assistant", "content": ""}
    session_data["history"].append(assistant_msg)

    # Emit initial state so clients can render immediately
    focus_image_urls, focus_image_source = _extract_focus_image_urls(
        wrong_item_context=wrong_item_context
    )
    payload = ChatResponse(
        messages=session_data["history"],
        session_id=session_id,
        retry_after_ms=None,
        cross_subject_flag=None,
        focus_image_urls=focus_image_urls,
        focus_image_source=focus_image_source,
    )
    yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")

    buffer = ""
    last_emit = time.monotonic()
    heartbeat_interval = float(getattr(settings, "chat_heartbeat_interval_seconds", 30.0) or 30.0)
    idle_disconnect_seconds = float(
        getattr(settings, "chat_idle_disconnect_seconds", 0.0) or 0.0
    )
    producer_join_timeout_seconds = float(
        getattr(settings, "chat_producer_join_timeout_seconds", 1.0) or 1.0
    )
    # "Idle" means: no LLM-produced chunks/events (heartbeat does NOT count).
    last_llm_item_m = time.monotonic()
    first_llm_output_logged = False
    idle_disconnected = False
    while True:
        try:
            item = await asyncio.wait_for(q.get(), timeout=heartbeat_interval)
        except asyncio.TimeoutError:
            # keep connection alive during long thinking
            if (
                idle_disconnect_seconds > 0
                and (time.monotonic() - last_llm_item_m) >= idle_disconnect_seconds
            ):
                idle_disconnected = True
                log_event(
                    logger,
                    "chat_sse_idle_disconnect",
                    request_id=request_id,
                    session_id=session_id,
                    idle_ms=int((time.monotonic() - last_llm_item_m) * 1000),
                    idle_disconnect_seconds=idle_disconnect_seconds,
                )
                break
            yield f'event: heartbeat\ndata: {{"timestamp":"{_now_iso_utc()}"}}\n\n'.encode(
                "utf-8"
            )
            continue

        if item is DONE:
            break
        if not first_llm_output_logged:
            kind = "text"
            if isinstance(item, dict) and item.get("event"):
                kind = "event"
            elif isinstance(item, dict) and item.get("error"):
                kind = "error"
            log_event(
                logger,
                "chat_llm_first_output",
                request_id=request_id,
                session_id=session_id,
                kind=kind,
                first_output_ms=int((time.monotonic() - llm_stream_started_m) * 1000),
                first_output_total_ms=int((time.monotonic() - started_m) * 1000),
            )
            first_llm_output_logged = True
        last_llm_item_m = time.monotonic()
        if isinstance(item, dict) and item.get("event"):
            evt = item.get("event")
            data = json.dumps(item.get("data") or {}, ensure_ascii=False)
            yield f"event: {evt}\ndata: {data}\n\n".encode("utf-8")
            continue
        if isinstance(item, dict) and item.get("error"):
            raise RuntimeError(item.get("error"))

        chunk = str(item)
        buffer += chunk
        assistant_msg["content"] = _format_math_for_display(buffer)

        # throttle event frequency
        now_m = time.monotonic()
        if now_m - last_emit >= 0.25 or chunk.endswith(("。", "！", "？", "\n")):
            payload = ChatResponse(
                messages=session_data["history"],
                session_id=session_id,
                retry_after_ms=None,
                cross_subject_flag=None,
                focus_image_urls=focus_image_urls,
                focus_image_source=focus_image_source,
            )
            yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")
            last_emit = now_m

    # Ensure final content is emitted
    payload = ChatResponse(
        messages=session_data["history"],
        session_id=session_id,
        retry_after_ms=None,
        cross_subject_flag=None,
        focus_image_urls=focus_image_urls,
        focus_image_source=focus_image_source,
    )
    yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")

    # Persist session
    session_data["interaction_count"] = current_turn + 1
    session_data["updated_at"] = _now_ts()
    try:
        from homework_agent.security.safety import sanitize_session_data_for_persistence

        sanitize_session_data_for_persistence(session_data)
    except Exception as e:
        logger.debug(f"Sanitizing session for persistence failed (best-effort): {e}")
    save_session(session_id, session_data)

    # Status: keep it simple for now
    log_event(
        logger,
        "chat_done",
        request_id=request_id,
        session_id=session_id,
        status="continue",
        idle_disconnected=bool(idle_disconnected),
        elapsed_ms=int((time.monotonic() - started_m) * 1000),
    )
    yield f'event: done\ndata: {{"status":"continue","session_id":"{session_id}"}}\n\n'.encode(
        "utf-8"
    )
    try:
        await asyncio.wait_for(producer_task, timeout=producer_join_timeout_seconds)
    except asyncio.TimeoutError:
        producer_task.cancel()
        log_event(
            logger,
            "chat_sse_producer_join_timeout",
            request_id=request_id,
            session_id=session_id,
            timeout_seconds=producer_join_timeout_seconds,
            level="warning",
        )
