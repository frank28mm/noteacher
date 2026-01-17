"""
Grade worker process.

Run:
  source .venv/bin/activate
  export PYTHONPATH=/path/to/project
  export REDIS_URL=redis://localhost:6379/0
  export REQUIRE_REDIS=1
  python3 -m homework_agent.workers.grade_worker

Notes:
- Consumes `grade:queue` and updates `job:{job_id}` in the shared cache (Redis).
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from homework_agent.utils.logging_setup import setup_file_logging, silence_noisy_loggers
from homework_agent.utils.settings import get_settings
from homework_agent.utils.observability import log_event
from homework_agent.models.schemas import GradeRequest, Subject
from homework_agent.api.grade import perform_grading
from homework_agent.services.grade_queue import (
    get_redis_client,
    queue_key,
    load_job_request,
    set_job_status,
    GradeJob,
)
from homework_agent.services.facts_queue import enqueue_facts_job
from homework_agent.api.session import IDP_TTL_HOURS
from homework_agent.api.session import (
    get_question_bank,
    persist_question_bank,
    save_mistakes,
)
from homework_agent.core.qbank import build_question_bank, build_question_bank_from_vision_raw_text
from homework_agent.core.question_cards import (
    build_question_cards_from_questions_list,
    build_question_cards_from_questions_map,
    make_card_item_id,
    merge_question_cards,
    sort_question_cards,
)
from homework_agent.core.review_cards_policy import pick_review_candidates
from homework_agent.services.autonomous_tools import ocr_question_cards
from homework_agent.services.review_cards_queue import enqueue_review_card_job
from homework_agent.utils.submission_store import update_submission_after_grade
from homework_agent.services.quota_service import bt_from_usage, charge_bt_spendable

logger = logging.getLogger(__name__)


class _Stopper:
    stop = False


def _install_signal_handlers(stopper: _Stopper) -> None:
    def _handle(signum, frame):  # noqa: ARG001
        stopper.stop = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def _iso_now() -> str:
    return datetime.now().isoformat()


def _subject_value(subject: Any) -> str:
    if isinstance(subject, Subject):
        return subject.value
    try:
        return str(getattr(subject, "value", subject))
    except Exception:
        return str(subject)


def _result_items_to_dicts(items: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in items or []:
        if hasattr(it, "model_dump"):
            out.append(it.model_dump())
        elif isinstance(it, dict):
            out.append(dict(it))
        else:
            try:
                out.append(dict(it))
            except Exception:
                continue
    return out


def _compute_uncertain_count(questions: Any) -> int:
    if not isinstance(questions, list):
        return 0
    n = 0
    for q in questions:
        if not isinstance(q, dict):
            continue
        if str(q.get("verdict") or "").strip().lower() == "uncertain":
            n += 1
    return n


def _needs_review(*, warnings: List[str], uncertain_count: int) -> bool:
    if uncertain_count > 0:
        return True
    for w in warnings or []:
        s = str(w).lower()
        if "needs_review" in s or "复核" in s or "依据不足" in s:
            return True
    return False


def _merge_questions_with_page_context(
    *,
    agg: Dict[str, Any],
    page_questions: Dict[str, Any],
    page_index: int,
    page_image_url: str,
    collisions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    merged = dict(agg or {})
    for raw_k, raw_v in (page_questions or {}).items():
        if not raw_k or not isinstance(raw_v, dict):
            continue
        base_key = str(raw_k)
        q = dict(raw_v)
        q.setdefault("page_index", int(page_index))
        q.setdefault("page_no", int(page_index) + 1)
        if page_image_url:
            q.setdefault("page_image_url", str(page_image_url))
        q["question_number"] = base_key

        if base_key in merged:
            existing = merged.get(base_key)
            existing_page = (
                int(existing.get("page_index"))
                if isinstance(existing, dict) and existing.get("page_index") is not None
                else None
            )
            if existing_page is not None and existing_page != int(page_index):
                alt_key = f"{base_key}@p{int(page_index)+1}"
                suffix = 2
                while alt_key in merged:
                    alt_key = f"{base_key}@p{int(page_index)+1}#{suffix}"
                    suffix += 1
                q["question_number"] = alt_key
                merged[alt_key] = q
                collisions.append(
                    {
                        "question_number": base_key,
                        "resolved_as": alt_key,
                        "page_index": int(page_index),
                    }
                )
                continue

        merged[base_key] = q
    return merged


def _now_job_payload(
    *,
    status: str,
    req_obj: Dict[str, Any],
    total_pages: int,
    done_pages: int,
    page_summaries: List[Dict[str, Any]],
    question_cards: Optional[List[Dict[str, Any]]] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    started: Optional[float] = None,
    finished: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": str(status),
        "created_at": _iso_now(),
        "request": req_obj,
        "result": result,
        "error": error,
        "total_pages": int(total_pages) if total_pages else None,
        "done_pages": int(done_pages) if total_pages else None,
        "page_summaries": list(page_summaries) if total_pages else None,
        "question_cards": question_cards if question_cards is not None else None,
    }
    # Convenience: surface submission_id/upload_id at top-level for clients (Result/AI Tutor).
    try:
        sid = str((req_obj or {}).get("upload_id") or "").strip()
        if sid:
            payload["submission_id"] = sid
    except Exception:
        pass
    if started is not None:
        try:
            payload["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        except Exception:
            pass
    if finished:
        payload["finished_at"] = _iso_now()
    return payload


def _concat_vision_raw_text_pages(pages: List[Tuple[int, str]]) -> str:
    parts: List[str] = []
    for idx, text in sorted(pages, key=lambda x: x[0]):
        t = str(text or "").strip()
        if not t:
            continue
        parts.append(f"### Page {idx+1}\n{t}")
    return "\n\n".join(parts).strip()


def _maybe_bill_grade_job(
    *,
    user_id: str,
    request_id: Optional[str],
    session_id: str,
    idempotency_key: Optional[str],
    prompt_tokens: int,
    completion_tokens: int,
    model: Optional[str],
) -> None:
    settings = get_settings()
    if str(getattr(settings, "auth_mode", "dev") or "dev").strip().lower() == "dev":
        return
    bt_cost = bt_from_usage(
        prompt_tokens=int(prompt_tokens or 0),
        completion_tokens=int(completion_tokens or 0),
    )
    ok, err = charge_bt_spendable(
        user_id=str(user_id),
        bt_cost=int(bt_cost),
        idempotency_key=str(idempotency_key or "").strip() or None,
        request_id=str(request_id or "").strip() or None,
        endpoint="/api/v1/grade",
        stage="grade",
        model=str(model or "").strip() or None,
        usage={
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "total_tokens": int(prompt_tokens or 0) + int(completion_tokens or 0),
        },
    )
    if not ok:
        log_event(
            logger,
            "quota_charge_failed",
            level="warning",
            request_id=request_id,
            session_id=session_id,
            user_id=str(user_id),
            endpoint="/api/v1/grade",
            stage="grade",
            error=str(err or ""),
        )


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO)
    )
    silence_noisy_loggers()
    if getattr(settings, "log_to_file", True):
        level = getattr(logging, settings.log_level.upper(), logging.INFO)
        setup_file_logging(
            log_file_path="logs/grade_worker.log",
            level=level,
            logger_names=["", "homework_agent"],
        )

    client = get_redis_client()
    if client is None:
        logger.error(
            "REDIS_URL not configured or redis unavailable; cannot start grade worker."
        )
        return 2

    qkey = queue_key()
    ttl_seconds = int(IDP_TTL_HOURS * 3600)
    stopper = _Stopper()
    _install_signal_handlers(stopper)

    log_event(logger, "grade_worker_started", queue=qkey)
    while not stopper.stop:
        try:
            item = client.brpop(qkey, timeout=2)
            if not item:
                continue
            _, raw = item
            job = GradeJob.from_json(
                raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            )
            if not job.job_id:
                continue

            payload = load_job_request(job.job_id) or {}
            req_obj = (
                payload.get("grade_request") if isinstance(payload, dict) else None
            )
            provider = payload.get("provider") if isinstance(payload, dict) else None
            provider = str(provider or job.provider or "").strip() or "ark"
            grade_image_input_variant = (
                payload.get("grade_image_input_variant")
                if isinstance(payload, dict)
                else None
            )
            idempotency_key = (
                str(payload.get("idempotency_key") or "").strip()
                if isinstance(payload, dict)
                else ""
            ) or None
            grade_image_input_variant = (
                str(grade_image_input_variant).strip().lower()
                if grade_image_input_variant is not None
                else ""
            ) or None
            if not isinstance(req_obj, dict):
                # Mark failed so clients can see it.
                set_job_status(
                    job.job_id,
                    {
                        "status": "failed",
                        "created_at": _iso_now(),
                        "request": None,
                        "result": None,
                        "error": "job request payload missing",
                        "finished_at": _iso_now(),
                    },
                    ttl_seconds=ttl_seconds,
                )
                continue

            set_job_status(
                job.job_id,
                {
                    "status": "running",
                    "created_at": _iso_now(),
                    "request": req_obj,
                    "result": None,
                    "total_pages": (
                        len(req_obj.get("images") or [])
                        if isinstance(req_obj, dict)
                        and isinstance(req_obj.get("images"), list)
                        else None
                    ),
                    "done_pages": (
                        0
                        if isinstance(req_obj, dict)
                        and isinstance(req_obj.get("images"), list)
                        and len(req_obj.get("images") or []) > 0
                        else None
                    ),
                    "page_summaries": (
                        []
                        if isinstance(req_obj, dict)
                        and isinstance(req_obj.get("images"), list)
                        and len(req_obj.get("images") or []) > 0
                        else None
                    ),
                },
                ttl_seconds=ttl_seconds,
            )
            log_event(
                logger,
                "grade_job_start",
                request_id=job.request_id,
                session_id=job.session_id,
                job_id=job.job_id,
                provider=provider,
            )

            started = time.monotonic()
            try:
                req = GradeRequest(**req_obj)
                if grade_image_input_variant:
                    try:
                        setattr(
                            req, "_grade_image_input_variant", grade_image_input_variant
                        )
                    except Exception:
                        pass

                page_image_urls: List[str] = [
                    str(getattr(img, "url", "") or "").strip()
                    for img in (getattr(req, "images", None) or [])
                    if str(getattr(img, "url", "") or "").strip()
                ]
                total_pages = max(0, len(getattr(req, "images", None) or []))
                subj_value = _subject_value(getattr(req, "subject", "math"))

                # A-6: Multi-page progressive experience (single job + partial output).
                if total_pages > 1:
                    page_summaries: List[Dict[str, Any]] = []
                    agg_wrong_items: List[Dict[str, Any]] = []
                    agg_questions: List[Dict[str, Any]] = []
                    agg_warnings: List[str] = []
                    vision_pages: List[Tuple[int, str]] = []
                    collisions: List[Dict[str, Any]] = []
                    cards_by_id: Dict[str, Dict[str, Any]] = {}
                    total_blank_count = 0
                    total_prompt_tokens = 0
                    total_completion_tokens = 0

                    agg_bank: Dict[str, Any] = {
                        "session_id": str(req.session_id or job.session_id or ""),
                        "subject": subj_value,
                        "page_image_urls": [u for u in page_image_urls if u],
                        "vision_raw_text": "",
                        "questions": {},
                        "meta": {
                            "pages_total": int(total_pages),
                            "pages_done": 0,
                        },
                    }

                    set_job_status(
                        job.job_id,
                        _now_job_payload(
                            status="running",
                            req_obj=req_obj,
                            total_pages=int(total_pages),
                            done_pages=0,
                            page_summaries=[],
                            question_cards=[],
                        ),
                        ttl_seconds=ttl_seconds,
                    )

                    for page_index, img in enumerate(getattr(req, "images", None) or []):
                        page_url = str(getattr(img, "url", "") or "").strip()
                        req_page = req.model_copy(update={"images": [img]})

                        # A-7 Layer 1: placeholder cards (best-effort, do not block grading on failures).
                        if page_url:
                            try:
                                ocr_res = ocr_question_cards(
                                    image=page_url, provider=str(provider or "ark")
                                )
                                ocr_text = (
                                    str(ocr_res.get("text") or "").strip()
                                    if isinstance(ocr_res, dict)
                                    else ""
                                )
                                if ocr_text:
                                    vision_qbank = build_question_bank_from_vision_raw_text(
                                        session_id=str(req.session_id or job.session_id or ""),
                                        subject=req.subject,
                                        vision_raw_text=ocr_text,
                                        page_image_urls=[page_url],
                                    )
                                    placeholders = build_question_cards_from_questions_map(
                                        page_index=int(page_index),
                                        questions=(
                                            vision_qbank.get("questions")
                                            if isinstance(vision_qbank, dict)
                                            else {}
                                        ),
                                        card_state="placeholder",
                                    )
                                    cards_by_id = merge_question_cards(
                                        cards_by_id, placeholders
                                    )
                                    set_job_status(
                                        job.job_id,
                                        _now_job_payload(
                                            status="running",
                                            req_obj=req_obj,
                                            total_pages=int(total_pages),
                                            done_pages=int(len(page_summaries)),
                                            page_summaries=page_summaries,
                                            question_cards=sort_question_cards(cards_by_id),
                                            started=started,
                                        ),
                                        ttl_seconds=ttl_seconds,
                                    )
                                    log_event(
                                        logger,
                                        "grade_job_page_placeholders_ready",
                                        request_id=job.request_id,
                                        session_id=job.session_id,
                                        job_id=job.job_id,
                                        page_index=int(page_index),
                                        cards=len(placeholders),
                                        source=str(ocr_res.get("source") or "network"),
                                    )
                            except Exception as e:
                                log_event(
                                    logger,
                                    "grade_job_page_placeholders_failed",
                                    level="warning",
                                    request_id=job.request_id,
                                    session_id=job.session_id,
                                    job_id=job.job_id,
                                    page_index=int(page_index),
                                    error_type=e.__class__.__name__,
                                    error=str(e),
                                )

                        page_started = time.monotonic()
                        page_result = asyncio.run(perform_grading(req_page, provider))
                        page_elapsed_ms = int((time.monotonic() - page_started) * 1000)

                        page_wrong_items = _result_items_to_dicts(
                            getattr(page_result, "wrong_items", None)
                        )
                        page_questions_list = getattr(page_result, "questions", None)
                        if not isinstance(page_questions_list, list):
                            page_questions_list = []

                        # A-7 Layer 2: verdict cards (page batch update).
                        verdict_cards, blank_count = build_question_cards_from_questions_list(
                            page_index=int(page_index),
                            questions=[q for q in page_questions_list if isinstance(q, dict)],
                            card_state="verdict_ready",
                        )
                        total_blank_count += int(blank_count)
                        cards_by_id = merge_question_cards(cards_by_id, verdict_cards)
                        blank_item_ids = {
                            str(c.get("item_id") or "").strip()
                            for c in verdict_cards
                            if isinstance(c, dict) and c.get("answer_state") == "blank"
                        }

                        # Layer 3: enqueue review cards for a small set of visually risky items.
                        settings = get_settings()
                        if bool(getattr(settings, "grade_review_cards_enabled", True)):
                            try:
                                max_per_page = int(
                                    getattr(settings, "grade_review_cards_max_per_page", 2) or 0
                                )
                            except Exception:
                                max_per_page = 2
                            try:
                                candidates = pick_review_candidates(
                                    subject=req.subject,
                                    page_index=int(page_index),
                                    questions=[q for q in page_questions_list if isinstance(q, dict)],
                                    max_per_page=max_per_page,
                                )
                            except Exception:
                                candidates = []
                            for cand in candidates or []:
                                if cand.item_id in blank_item_ids:
                                    continue
                                # Mark as review pending in cards (front-end flips later).
                                cards_by_id = merge_question_cards(
                                    cards_by_id,
                                    [
                                        {
                                            "item_id": cand.item_id,
                                            "card_state": "review_pending",
                                            "review_reasons": list(cand.review_reasons or [])[:8],
                                        }
                                    ],
                                )
                                enqueue_review_card_job(
                                    job_id=job.job_id,
                                    session_id=str(req.session_id or job.session_id or ""),
                                    request_id=job.request_id,
                                    subject=str(subj_value),
                                    page_index=int(page_index),
                                    question_number=str(cand.question_number),
                                    item_id=str(cand.item_id),
                                    review_reasons=list(cand.review_reasons or [])[:8],
                                    page_image_url=str(page_url or "").strip() or None,
                                    question_content=(
                                        str(
                                            next(
                                                (
                                                    q.get("question_content")
                                                    for q in page_questions_list
                                                    if isinstance(q, dict)
                                                    and str(q.get("question_number") or "").strip() == str(cand.question_number)
                                                ),
                                                "",
                                            )
                                        ).strip()
                                        or None
                                    ),
                                )

                        # Attach page context to wrong items and ensure stable per-page item_ids for demo selection.
                        page_item_ids: List[str] = []
                        page_wrong_items_filtered: List[Dict[str, Any]] = []
                        for wi in page_wrong_items:
                            if not isinstance(wi, dict):
                                continue
                            wi["page_index"] = int(page_index)
                            wi["page_no"] = int(page_index) + 1
                            if page_url:
                                wi["page_image_url"] = page_url
                            item_id = make_card_item_id(
                                page_index=int(page_index),
                                question_number=wi.get("question_number"),
                            )
                            wi["item_id"] = item_id
                            if item_id in blank_item_ids:
                                continue
                            page_item_ids.append(item_id)
                            page_wrong_items_filtered.append(wi)

                        # Attach page context to question list (used for final /grade result + chat hints).
                        for q in page_questions_list:
                            if not isinstance(q, dict):
                                continue
                            q.setdefault("page_index", int(page_index))
                            q.setdefault("page_no", int(page_index) + 1)
                            if page_url:
                                q.setdefault("page_image_url", page_url)
                            q["item_id"] = make_card_item_id(
                                page_index=int(page_index),
                                question_number=q.get("question_number") or q.get("question_index"),
                            )

                        # Aggregate wrong_items and warnings.
                        agg_wrong_items.extend(
                            [wi for wi in page_wrong_items_filtered if isinstance(wi, dict)]
                        )
                        agg_questions.extend(
                            [q for q in page_questions_list if isinstance(q, dict)]
                        )
                        page_warnings = list(getattr(page_result, "warnings", None) or [])
                        for w in page_warnings:
                            s = str(w).strip()
                            if s and s not in agg_warnings:
                                agg_warnings.append(s)

                        # Incremental qbank merge (union of done pages).
                        try:
                            page_bank = build_question_bank(
                                session_id=str(req.session_id or job.session_id or ""),
                                subject=req.subject,
                                questions=[q for q in page_questions_list if isinstance(q, dict)],
                                vision_raw_text=str(
                                    getattr(page_result, "vision_raw_text", None) or ""
                                ),
                                page_image_urls=[page_url] if page_url else [],
                                visual_facts_map=None,
                            )
                            page_questions = (
                                page_bank.get("questions") if isinstance(page_bank, dict) else None
                            )
                            page_questions = (
                                page_questions if isinstance(page_questions, dict) else {}
                            )

                            agg_questions_map = (
                                agg_bank.get("questions")
                                if isinstance(agg_bank.get("questions"), dict)
                                else {}
                            )
                            merged_questions = _merge_questions_with_page_context(
                                agg=agg_questions_map,
                                page_questions=page_questions,
                                page_index=int(page_index),
                                page_image_url=page_url,
                                collisions=collisions,
                            )
                            agg_bank["questions"] = merged_questions
                            agg_bank["page_image_urls"] = [u for u in page_image_urls if u]

                            vt = str(getattr(page_result, "vision_raw_text", None) or "").strip()
                            if vt:
                                vision_pages.append((int(page_index), vt))
                                agg_bank["vision_raw_text"] = _concat_vision_raw_text_pages(
                                    vision_pages
                                )

                            meta_now: Dict[str, Any] = {}
                            bank_now = get_question_bank(job.session_id) if job.session_id else None
                            if (
                                isinstance(bank_now, dict)
                                and isinstance(bank_now.get("meta"), dict)
                            ):
                                meta_now = dict(bank_now.get("meta") or {})
                            usage_now = (
                                meta_now.get("llm_usage")
                                if isinstance(meta_now, dict)
                                else None
                            )
                            if isinstance(usage_now, dict):
                                total_prompt_tokens += int(
                                    usage_now.get("prompt_tokens") or 0
                                )
                                total_completion_tokens += int(
                                    usage_now.get("completion_tokens") or 0
                                )
                            meta = (
                                agg_bank.get("meta")
                                if isinstance(agg_bank.get("meta"), dict)
                                else {}
                            )
                            meta.update({k: v for k, v in meta_now.items() if v is not None})
                            meta["pages_total"] = int(total_pages)
                            meta["pages_done"] = int(page_index) + 1
                            if collisions:
                                meta["question_number_collisions"] = list(collisions)[-50:]
                            agg_bank["meta"] = meta

                            persist_question_bank(
                                session_id=str(req.session_id or job.session_id or ""),
                                bank=agg_bank,
                                grade_status="running",
                                grade_summary=f"批改进行中：已完成 {int(page_index)+1}/{total_pages} 页",
                                grade_warnings=list(
                                    dict.fromkeys(
                                        [
                                            *agg_warnings,
                                            f"批改尚未完成：当前仅完成 {int(page_index)+1}/{total_pages} 页（辅导仅基于已完成页）",
                                        ]
                                    )
                                ),
                                request_id=job.request_id,
                                timings_ms=None,
                            )
                            save_mistakes(
                                str(req.session_id or job.session_id or ""),
                                agg_wrong_items,
                            )
                        except Exception as e:
                            log_event(
                                logger,
                                "grade_worker_partial_qbank_failed",
                                level="warning",
                                request_id=job.request_id,
                                session_id=job.session_id,
                                job_id=job.job_id,
                                page_index=int(page_index),
                                error_type=e.__class__.__name__,
                                error=str(e),
                            )

                        wrong_count = int(len(page_wrong_items_filtered))
                        uncertain_count = 0
                        for c in verdict_cards:
                            if not isinstance(c, dict):
                                continue
                            if c.get("answer_state") == "blank":
                                continue
                            if str(c.get("verdict") or "").strip().lower() == "uncertain":
                                uncertain_count += 1
                        needs_review = _needs_review(
                            warnings=[str(w) for w in page_warnings if str(w).strip()],
                            uncertain_count=uncertain_count,
                        )

                        page_summaries.append(
                            {
                                "page_index": int(page_index),
                                "wrong_count": wrong_count,
                                "uncertain_count": uncertain_count,
                                "blank_count": int(blank_count),
                                "needs_review": bool(needs_review),
                                "warnings": [str(w) for w in page_warnings if str(w).strip()][
                                    :10
                                ],
                                # Demo helper: allow "进入辅导（本页）" without extra endpoints.
                                "wrong_item_ids": page_item_ids[:30],
                                "page_elapsed_ms": int(page_elapsed_ms),
                            }
                        )

                        set_job_status(
                            job.job_id,
                            _now_job_payload(
                                status="running",
                                req_obj=req_obj,
                                total_pages=int(total_pages),
                                done_pages=int(page_index) + 1,
                                page_summaries=page_summaries,
                                question_cards=sort_question_cards(cards_by_id),
                                started=started,
                            ),
                            ttl_seconds=ttl_seconds,
                        )
                        log_event(
                            logger,
                            "grade_job_page_done",
                            request_id=job.request_id,
                            session_id=job.session_id,
                            job_id=job.job_id,
                            page_index=int(page_index),
                            done_pages=int(page_index) + 1,
                            total_pages=int(total_pages),
                            page_elapsed_ms=int(page_elapsed_ms),
                        )

                    # Normalize `questions[*].question_content` to the OCR-grounded "full text"
                    # (stem + options) so UI can consistently show full stems and clamp in the frontend.
                    try:
                        from homework_agent.core.qbank_parser import (
                            _normalize_question_number as _norm_qn,
                        )

                        qmap = (
                            agg_bank.get("questions")
                            if isinstance(agg_bank.get("questions"), dict)
                            else {}
                        )

                        def _looks_like_placeholder(s: str) -> bool:
                            t = (s or "").strip()
                            if not t:
                                return True
                            return t.startswith("（批改未完成") or t.startswith("（未提取到")

                        for q in agg_questions:
                            if not isinstance(q, dict):
                                continue
                            qn_raw = q.get("question_number") or q.get("question_index")
                            qn = str(qn_raw or "").strip()
                            qn_key = _norm_qn(qn) or qn
                            src = qmap.get(qn_key) or qmap.get(qn)
                            if not isinstance(src, dict):
                                continue
                            full = src.get("question_text") or src.get("question_content")
                            full_s = str(full or "").strip()
                            if full_s and not _looks_like_placeholder(full_s):
                                q["question_content"] = full_s
                            # Prefer OCR/parsed options if missing (helps UI reconstruct full text).
                            if q.get("options") is None and src.get("options") is not None:
                                q["options"] = src.get("options")

                        # Keep job.question_cards aligned with the same full text (ResultSummary may render from /jobs/{job_id}).
                        for _item_id, c in list((cards_by_id or {}).items()):
                            if not isinstance(c, dict):
                                continue
                            qn = str(c.get("question_number") or "").strip()
                            if not qn:
                                continue
                            qn_key = _norm_qn(qn) or qn
                            src = qmap.get(qn_key) or qmap.get(qn)
                            if not isinstance(src, dict):
                                continue
                            full = src.get("question_text") or src.get("question_content")
                            full_s = str(full or "").strip()
                            if full_s and not _looks_like_placeholder(full_s):
                                c["question_content"] = full_s
                                cards_by_id[str(c.get("item_id") or _item_id)] = c
                    except Exception:
                        pass

                    grade_result_dict: Dict[str, Any] = {
                        "wrong_items": agg_wrong_items,
                        "summary": (
                            f"共 {total_pages} 页：错题 {len(agg_wrong_items)} 道"
                            + (
                                f"（未作答 {int(total_blank_count)} 题）"
                                if int(total_blank_count) > 0
                                else ""
                            )
                        ),
                        "subject": subj_value,
                        "job_id": job.job_id,
                        "session_id": str(req.session_id or job.session_id or ""),
                        "status": "done",
                        "total_items": len([q for q in agg_questions if isinstance(q, dict)]) or None,
                        "wrong_count": len(agg_wrong_items),
                        "blank_count": int(total_blank_count),
                        "cross_subject_flag": None,
                        "warnings": agg_warnings,
                        "vision_raw_text": agg_bank.get("vision_raw_text") or None,
                        "visual_facts": None,
                        "figure_present": None,
                        "questions": agg_questions,
                    }

                    # Persist final qbank snapshot as done (overwrite running markers).
                    try:
                        meta = (
                            agg_bank.get("meta")
                            if isinstance(agg_bank.get("meta"), dict)
                            else {}
                        )
                        meta["pages_total"] = int(total_pages)
                        meta["pages_done"] = int(total_pages)
                        agg_bank["meta"] = meta
                        persist_question_bank(
                            session_id=str(req.session_id or job.session_id or ""),
                            bank=agg_bank,
                            grade_status="done",
                            grade_summary=str(grade_result_dict.get("summary") or "").strip(),
                            grade_warnings=agg_warnings,
                            request_id=job.request_id,
                            timings_ms=None,
                        )
                        save_mistakes(
                            str(req.session_id or job.session_id or ""),
                            agg_wrong_items,
                        )
                    except Exception as e:
                        log_event(
                            logger,
                            "grade_worker_finalize_qbank_failed",
                            level="warning",
                            request_id=job.request_id,
                            session_id=job.session_id,
                            job_id=job.job_id,
                            error_type=e.__class__.__name__,
                            error=str(e),
                        )

                    # Best-effort: persist Submission facts + enqueue derived facts job.
                    upload_id = str(getattr(req, "upload_id", "") or "").strip()
                    if upload_id and job.user_id:
                        try:
                            bank_now = (
                                get_question_bank(job.session_id)
                                if job.session_id
                                else None
                            )
                            meta_now = (
                                dict(bank_now.get("meta") or {})
                                if isinstance(bank_now, dict)
                                and isinstance(bank_now.get("meta"), dict)
                                else {}
                            )
                            meta_now = {k: v for k, v in meta_now.items() if v is not None}
                            update_submission_after_grade(
                                user_id=str(job.user_id),
                                submission_id=upload_id,
                                session_id=str(job.session_id),
                                request_id=job.request_id,
                                subject=subj_value,
                                page_image_urls=page_image_urls or None,
                                proxy_page_image_urls=None,
                                vision_raw_text=grade_result_dict.get("vision_raw_text"),
                                grade_result=grade_result_dict,
                                warnings=list(grade_result_dict.get("warnings") or []),
                                meta=meta_now or None,
                            )
                            enqueue_facts_job(
                                submission_id=upload_id,
                                user_id=str(job.user_id),
                                session_id=str(job.session_id),
                                request_id=job.request_id,
                            )
                            log_event(
                                logger,
                                "grade_worker_persisted_submission",
                                request_id=job.request_id,
                                session_id=job.session_id,
                                job_id=job.job_id,
                                submission_id=upload_id,
                            )
                        except Exception as e:
                            log_event(
                                logger,
                                "grade_worker_persist_submission_failed",
                                level="warning",
                                request_id=job.request_id,
                                session_id=job.session_id,
                                job_id=job.job_id,
                                submission_id=upload_id,
                                error_type=e.__class__.__name__,
                                error=str(e),
                            )

                    set_job_status(
                        job.job_id,
                        _now_job_payload(
                            status="done",
                            req_obj=req_obj,
                            total_pages=int(total_pages),
                            done_pages=int(total_pages),
                            page_summaries=page_summaries,
                            question_cards=sort_question_cards(cards_by_id),
                            result=grade_result_dict,
                            started=started,
                            finished=True,
                        ),
                        ttl_seconds=ttl_seconds,
                    )
                    log_event(
                        logger,
                        "grade_job_done",
                        request_id=job.request_id,
                        session_id=job.session_id,
                        job_id=job.job_id,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                    )
                    try:
                        bank_now = get_question_bank(job.session_id) if job.session_id else None
                        meta_now = (
                            (bank_now or {}).get("meta") if isinstance(bank_now, dict) else None
                        )
                        meta_now = meta_now if isinstance(meta_now, dict) else {}
                        _maybe_bill_grade_job(
                            user_id=str(job.user_id),
                            request_id=job.request_id,
                            session_id=str(job.session_id),
                            idempotency_key=idempotency_key or job.job_id,
                            prompt_tokens=int(total_prompt_tokens),
                            completion_tokens=int(total_completion_tokens),
                            model=str(meta_now.get("llm_model") or "") or None,
                        )
                    except Exception:
                        pass
                    continue

                # Single-page: keep existing behavior.
                result = asyncio.run(perform_grading(req, provider))

                # Best-effort: persist Submission facts + enqueue derived facts job.
                # NOTE: grade_homework endpoint does this after perform_grading, but worker path must do it too.
                upload_id = str(getattr(req, "upload_id", "") or "").strip()
                if upload_id and job.user_id:
                    try:
                        bank_now = (
                            get_question_bank(job.session_id)
                            if job.session_id
                            else None
                        )
                        meta_now = (
                            dict(bank_now.get("meta") or {})
                            if isinstance(bank_now, dict)
                            and isinstance(bank_now.get("meta"), dict)
                            else {}
                        )
                        # Keep meta small and non-null for audit/debug
                        meta_now = {k: v for k, v in meta_now.items() if v is not None}

                        page_image_urls = [
                            str(getattr(img, "url", "") or "").strip()
                            for img in (getattr(req, "images", None) or [])
                            if str(getattr(img, "url", "") or "").strip()
                        ]
                        subj = (
                            req.subject.value
                            if hasattr(req.subject, "value")
                            else str(req.subject)
                        )
                        update_submission_after_grade(
                            user_id=str(job.user_id),
                            submission_id=upload_id,
                            session_id=str(job.session_id),
                            request_id=job.request_id,
                            subject=subj,
                            page_image_urls=page_image_urls or None,
                            proxy_page_image_urls=None,
                            vision_raw_text=getattr(result, "vision_raw_text", None),
                            grade_result=(
                                result.model_dump()
                                if hasattr(result, "model_dump")
                                else {}
                            ),
                            warnings=list(getattr(result, "warnings", None) or []),
                            meta=meta_now or None,
                        )
                        enqueue_facts_job(
                            submission_id=upload_id,
                            user_id=str(job.user_id),
                            session_id=str(job.session_id),
                            request_id=job.request_id,
                        )
                        log_event(
                            logger,
                            "grade_worker_persisted_submission",
                            request_id=job.request_id,
                            session_id=job.session_id,
                            job_id=job.job_id,
                            submission_id=upload_id,
                        )
                    except Exception as e:
                        log_event(
                            logger,
                            "grade_worker_persist_submission_failed",
                            level="warning",
                            request_id=job.request_id,
                            session_id=job.session_id,
                            job_id=job.job_id,
                            submission_id=upload_id,
                            error_type=e.__class__.__name__,
                            error=str(e),
                        )

                # Keep session-scoped mistakes available for demo tutoring context selection.
                questions_list = getattr(result, "questions", None)
                if not isinstance(questions_list, list):
                    questions_list = []
                qc, blank_n = build_question_cards_from_questions_list(
                    page_index=0,
                    questions=[q for q in questions_list if isinstance(q, dict)],
                    card_state="verdict_ready",
                )
                blank_item_ids = {
                    str(c.get("item_id") or "").strip()
                    for c in qc
                    if isinstance(c, dict) and c.get("answer_state") == "blank"
                }
                wrong_items_dicts = _result_items_to_dicts(
                    getattr(result, "wrong_items", None)
                )
                wrong_items_filtered: List[Dict[str, Any]] = []
                for wi in wrong_items_dicts:
                    if not isinstance(wi, dict):
                        continue
                    wi["page_index"] = 0
                    wi["page_no"] = 1
                    wi["item_id"] = make_card_item_id(
                        page_index=0, question_number=wi.get("question_number")
                    )
                    if wi["item_id"] in blank_item_ids:
                        continue
                    wrong_items_filtered.append(wi)

                try:
                    save_mistakes(
                        str(req.session_id or job.session_id or ""),
                        wrong_items_filtered,
                    )
                except Exception:
                    pass

                uncertain_count = 0
                for c in qc:
                    if not isinstance(c, dict):
                        continue
                    if c.get("answer_state") == "blank":
                        continue
                    if str(c.get("verdict") or "").strip().lower() == "uncertain":
                        uncertain_count += 1
                warnings_list = [
                    str(w)
                    for w in (getattr(result, "warnings", None) or [])
                    if str(w).strip()
                ][:10]
                needs_review = _needs_review(
                    warnings=warnings_list,
                    uncertain_count=uncertain_count,
                )
                result_dict = (
                    result.model_dump() if hasattr(result, "model_dump") else {}
                )
                if isinstance(result_dict, dict):
                    result_dict["wrong_items"] = wrong_items_filtered
                    result_dict["wrong_count"] = int(len(wrong_items_filtered))
                    result_dict["blank_count"] = int(blank_n)
                try:
                    bank_now = get_question_bank(job.session_id) if job.session_id else None
                    meta_now = (
                        (bank_now or {}).get("meta") if isinstance(bank_now, dict) else None
                    )
                    meta_now = meta_now if isinstance(meta_now, dict) else {}
                    usage_now = meta_now.get("llm_usage") if isinstance(meta_now, dict) else None
                    if isinstance(usage_now, dict):
                        _maybe_bill_grade_job(
                            user_id=str(job.user_id),
                            request_id=job.request_id,
                            session_id=str(job.session_id),
                            idempotency_key=idempotency_key or job.job_id,
                            prompt_tokens=int(usage_now.get("prompt_tokens") or 0),
                            completion_tokens=int(usage_now.get("completion_tokens") or 0),
                            model=str(meta_now.get("llm_model") or "") or None,
                        )
                except Exception:
                    pass
                set_job_status(
                    job.job_id,
                    _now_job_payload(
                        status="done",
                        req_obj=req_obj,
                        total_pages=1,
                        done_pages=1,
                        page_summaries=[
                            {
                                "page_index": 0,
                                "wrong_count": int(len(wrong_items_filtered)),
                                "uncertain_count": int(uncertain_count),
                                "blank_count": int(blank_n),
                                "needs_review": bool(needs_review),
                                "warnings": warnings_list,
                            }
                        ],
                        question_cards=qc,
                        result=result_dict if isinstance(result_dict, dict) else None,
                        started=started,
                        finished=True,
                    ),
                    ttl_seconds=ttl_seconds,
                )
                log_event(
                    logger,
                    "grade_job_done",
                    request_id=job.request_id,
                    session_id=job.session_id,
                    job_id=job.job_id,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
            except Exception as e:
                set_job_status(
                    job.job_id,
                    {
                        "status": "failed",
                        "created_at": _iso_now(),
                        "request": req_obj,
                        "result": None,
                        "error": str(e),
                        "finished_at": _iso_now(),
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    },
                    ttl_seconds=ttl_seconds,
                )
                log_event(
                    logger,
                    "grade_job_failed",
                    level="warning",
                    request_id=job.request_id,
                    session_id=job.session_id,
                    job_id=job.job_id,
                    error_type=e.__class__.__name__,
                    error=str(e),
                )
        except Exception as e:  # pragma: no cover
            log_event(
                logger,
                "grade_worker_error",
                level="error",
                request_id=None,
                error_type=e.__class__.__name__,
                error=str(e),
            )
            logger.exception("Grade worker error: %s", e)
            time.sleep(1)

    log_event(logger, "grade_worker_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
