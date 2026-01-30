"""
Review Cards worker process.

Consumes `review_cards:queue` and updates `job:{job_id}.question_cards[]` in cache.

Goal:
- Produce "review_ready" evidence for visually risky questions without blocking /grade completion.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from datetime import datetime
from typing import Any, Dict, Optional

from homework_agent.api.session import get_question_index
from homework_agent.models.schemas import Subject, VisionProvider
from homework_agent.models.vision_facts import GateResult
from homework_agent.services.review_cards_queue import (
    ReviewCardJob,
    get_redis_client,
    queue_key,
    enqueue_review_card_job,
)
from homework_agent.services.vision_facts import (
    detect_scene_type,
    extract_visual_facts,
    gate_visual_facts,
    select_vfe_images,
)
from homework_agent.utils.cache import get_cache_store
from homework_agent.utils.logging_setup import setup_file_logging, silence_noisy_loggers
from homework_agent.utils.observability import log_event
from homework_agent.utils.settings import get_settings
from homework_agent.utils.supabase_image_proxy import _create_proxy_image_urls

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


async def _call_blocking_in_thread(fn, **kwargs):
    return await asyncio.to_thread(fn, **kwargs)


def _pick_qindex_refs_for_question(
    *, qindex: Dict[str, Any], question_number: str, page_index: int
) -> Optional[Dict[str, Any]]:
    if not isinstance(qindex, dict):
        return None
    qs = qindex.get("questions")
    if not isinstance(qs, dict):
        return None
    base_qn = str(question_number or "").split("@", 1)[0].split("#", 1)[0].strip()
    if not base_qn:
        return None
    entry = qs.get(base_qn)
    if not isinstance(entry, dict):
        return None
    pages = entry.get("pages")
    if not isinstance(pages, list):
        return entry
    # Filter to the requested page_index when possible.
    filtered = [
        p for p in pages if isinstance(p, dict) and p.get("page_index") == page_index
    ]
    if filtered:
        e = dict(entry)
        e["pages"] = filtered
        return e
    return entry


def _update_job_card(
    *,
    job_id: str,
    item_id: str,
    patch: Dict[str, Any],
    ttl_seconds: int,
) -> bool:
    cache = get_cache_store()
    job = cache.get(f"job:{job_id}")
    if not isinstance(job, dict):
        return False
    cards = job.get("question_cards")
    if not isinstance(cards, list):
        cards = []
    changed = False
    for i, c in enumerate(cards):
        if not isinstance(c, dict):
            continue
        if str(c.get("item_id") or "").strip() != str(item_id):
            continue
        merged = dict(c)
        merged.update({k: v for k, v in (patch or {}).items() if v is not None})
        cards[i] = merged
        changed = True
        break
    if not changed:
        return False
    job["question_cards"] = cards
    job["updated_at"] = _iso_now()
    cache.set(f"job:{job_id}", job, ttl_seconds=ttl_seconds)
    return True


async def _run_vfe_review(
    *,
    session_id: str,
    subject: Subject,
    question_number: str,
    page_index: int,
    page_image_url: Optional[str],
    qcontent: str,
    visual_risk: bool,
    user_text: str,
    timeout_s: float,
    request_id: Optional[str],
) -> Dict[str, Any]:
    focus: Dict[str, Any] = {
        "question_number": question_number,
        "page_image_url": page_image_url,
        "question_content": qcontent,
        "visual_risk": bool(visual_risk),
    }
    qindex = get_question_index(session_id) or {}
    refs = _pick_qindex_refs_for_question(
        qindex=qindex,
        question_number=question_number,
        page_index=int(page_index),
    )
    if isinstance(refs, dict) and refs:
        focus["image_refs"] = refs
    sel = select_vfe_images(focus_question=focus)
    if not sel.image_urls:
        return {"status": "skipped", "reason": "no_images"}

    settings = get_settings()
    prefer_ark = bool(settings.ark_api_key and settings.ark_base_url)
    provider = VisionProvider.DOUBAO if prefer_ark else VisionProvider.QWEN3
    image_urls = list(sel.image_urls)
    image_source = sel.image_source

    # For large page images, generate a lightweight proxy to reduce timeouts.
    if image_source == "page":
        proxy_urls = _create_proxy_image_urls(
            image_urls, session_id=session_id, prefix="vfe_proxy/"
        )
        if proxy_urls:
            image_urls = proxy_urls
            image_source = "page_proxy"

    scene_type = detect_scene_type(
        subject=subject,
        user_text=user_text,
        question_content=qcontent,
        visual_risk=bool(visual_risk),
        has_figure_slice=bool(image_source == "slice_figure"),
    )
    if request_id:
        log_event(
            logger,
            "review_cards_vfe_start",
            level="warning",
            request_id=request_id,
            session_id=session_id,
            focus_qn=str(question_number),
            scene_type=scene_type.value,
            image_source=image_source,
            budget_s=int(timeout_s),
        )

    try:
        facts, repaired_json, raw = await asyncio.wait_for(
            _call_blocking_in_thread(
                extract_visual_facts,
                image_urls=image_urls,
                scene_type=scene_type,
                provider=provider,
            ),
            timeout=float(timeout_s),
        )
    except asyncio.TimeoutError:
        gate = GateResult(
            passed=False,
            trigger="vision_timeout",
            critical_unknowns_hit=[],
            user_facing_message=f"看图超时（{int(timeout_s)}s），暂无法确认关键图形信息。",
            repaired_json=False,
        )
        return {
            "status": "failed",
            "relook_error": f"VFE fail-closed: {gate.trigger}",
            "vfe_gate": gate.model_dump(),
            "vfe_scene_type": scene_type.value,
            "vfe_image_source": image_source,
            "vfe_image_urls": image_urls[:2],
        }
    except Exception as e:
        return {
            "status": "failed",
            "relook_error": f"VFE error: {e}",
        }

    if not facts:
        gate = GateResult(
            passed=False,
            trigger="no_facts",
            critical_unknowns_hit=[],
            user_facing_message="我没能从图片里稳定提取到结构化事实，暂无法复核。",
            repaired_json=bool(repaired_json),
        )
        return {
            "status": "failed",
            "relook_error": f"VFE fail-closed: {gate.trigger}",
            "vfe_gate": gate.model_dump(),
            "vfe_scene_type": scene_type.value,
            "vfe_image_source": image_source,
            "vfe_image_urls": image_urls[:2],
            "raw_preview": (raw or "")[:800] if raw else None,
        }

    gate = gate_visual_facts(
        facts=facts,
        scene_type=scene_type,
        visual_risk=visual_risk,
        user_text=user_text,
        image_source=image_source,
        repaired_json=bool(repaired_json),
    )
    payload: Dict[str, Any] = {
        "status": "ok" if gate.passed else "failed",
        "visual_facts": facts.model_dump(),
        "vfe_gate": gate.model_dump(),
        "vfe_scene_type": scene_type.value,
        "vfe_image_source": image_source,
        "vfe_image_urls": image_urls[:2],
        "repaired_json": bool(repaired_json),
    }

    if gate.passed:
        # Build a short, UI-friendly evidence summary (deterministic, no extra LLM call).
        preview_lines: list[str] = []
        try:
            bundle = facts.facts
            for line in (bundle.lines or [])[:6]:
                parts = [
                    getattr(line, "name", None),
                    getattr(line, "direction", None),
                    getattr(line, "relative", None),
                ]
                preview_lines.append("- " + " ".join([str(p) for p in parts if p]))
            for ang in (bundle.angles or [])[:6]:
                parts = [
                    getattr(ang, "name", None),
                    (
                        f"at {getattr(ang, 'at', None)}"
                        if getattr(ang, "at", None)
                        else None
                    ),
                    (
                        f"between {','.join(getattr(ang, 'between', None) or [])}"
                        if getattr(ang, "between", None)
                        else None
                    ),
                    f"side={getattr(ang, 'transversal_side', None)}",
                    f"between_lines={getattr(ang, 'between_lines', None)}",
                ]
                preview_lines.append("- " + " ".join([str(p) for p in parts if p]))
        except Exception:
            preview_lines = []
        if not preview_lines and raw:
            preview_lines = [raw[:800]]
        payload["review_summary"] = "\n".join(preview_lines)[:2200]
    else:
        payload["relook_error"] = f"VFE fail-closed: {gate.trigger}"

    if request_id:
        log_event(
            logger,
            "review_cards_vfe_done",
            level="warning",
            request_id=request_id,
            session_id=session_id,
            focus_qn=str(question_number),
            scene_type=scene_type.value,
            passed=bool(gate.passed),
            trigger=str(gate.trigger),
            image_source=image_source,
            confidence=float(getattr(facts, "confidence", 0.0) or 0.0),
            repaired_json=bool(repaired_json),
        )
    return payload


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO)
    )
    silence_noisy_loggers()
    if getattr(settings, "log_to_file", True):
        level = getattr(logging, settings.log_level.upper(), logging.INFO)
        setup_file_logging(
            log_file_path="logs/review_cards_worker.log",
            level=level,
            logger_names=["", "homework_agent"],
        )

    client = get_redis_client()
    if client is None:
        logger.error(
            "REDIS_URL not configured or redis unavailable; cannot start review cards worker."
        )
        return 2

    qkey = queue_key()
    stopper = _Stopper()
    _install_signal_handlers(stopper)
    ttl_seconds = 24 * 3600
    try:
        ttl_seconds = int(
            getattr(settings, "slice_ttl_seconds", ttl_seconds) or ttl_seconds
        )
    except Exception:
        ttl_seconds = 24 * 3600

    max_attempts = 3
    budget = max(
        10, int(getattr(settings, "grade_review_cards_timeout_seconds", 60) or 60)
    )
    log_event(logger, "review_cards_worker_started", queue=qkey, budget_s=budget)

    while not stopper.stop:
        try:
            item = client.brpop(qkey, timeout=2)
            if not item:
                continue
            _, raw = item
            job = ReviewCardJob.from_json(
                raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            )
            if not job.job_id or not job.session_id or not job.item_id:
                continue

            # Mark review as pending (in case it was enqueued before the UI saw it).
            _update_job_card(
                job_id=job.job_id,
                item_id=job.item_id,
                patch={
                    "card_state": "review_pending",
                    "review_reasons": job.review_reasons[:8],
                    "review_updated_at": _iso_now(),
                },
                ttl_seconds=ttl_seconds,
            )

            # Best-effort: wait for qindex slices if not ready (requeue a few times).
            qidx = get_question_index(job.session_id) or {}
            has_slices = False
            try:
                refs = _pick_qindex_refs_for_question(
                    qindex=qidx,
                    question_number=job.question_number,
                    page_index=int(job.page_index),
                )
                if isinstance(refs, dict) and refs.get("pages"):
                    has_slices = True
            except Exception:
                has_slices = False

            if not has_slices and int(job.attempt) < max_attempts:
                # Re-enqueue to give qindex worker time; do not spin tight.
                time.sleep(1.5 + 0.5 * int(job.attempt))
                enqueue_review_card_job(
                    job_id=job.job_id,
                    session_id=job.session_id,
                    request_id=job.request_id,
                    subject=job.subject,
                    page_index=int(job.page_index),
                    question_number=job.question_number,
                    item_id=job.item_id,
                    review_reasons=list(job.review_reasons or []),
                    page_image_url=job.page_image_url,
                    question_content=job.question_content,
                    attempt=int(job.attempt) + 1,
                )
                continue

            subject = Subject.MATH
            try:
                subject = Subject(str(job.subject or "math").strip().lower())
            except Exception:
                subject = Subject.MATH

            payload = asyncio.run(
                _run_vfe_review(
                    session_id=job.session_id,
                    subject=subject,
                    question_number=str(job.question_number),
                    page_index=int(job.page_index),
                    page_image_url=job.page_image_url,
                    qcontent=str(job.question_content or ""),
                    visual_risk=True,
                    user_text="",
                    timeout_s=float(budget),
                    request_id=job.request_id,
                )
            )

            ok = bool(payload.get("status") == "ok")
            patch = {
                "card_state": "review_ready" if ok else "review_failed",
                "review_updated_at": _iso_now(),
                "review_summary": payload.get("review_summary"),
                "relook_error": payload.get("relook_error"),
                "vfe_gate": payload.get("vfe_gate"),
                "vfe_scene_type": payload.get("vfe_scene_type"),
                "vfe_image_source": payload.get("vfe_image_source"),
                "vfe_image_urls": payload.get("vfe_image_urls"),
                "visual_facts": payload.get("visual_facts"),
            }
            _update_job_card(
                job_id=job.job_id,
                item_id=job.item_id,
                patch=patch,
                ttl_seconds=ttl_seconds,
            )
            log_event(
                logger,
                "review_cards_item_done",
                request_id=job.request_id,
                session_id=job.session_id,
                job_id=job.job_id,
                item_id=job.item_id,
                question_number=str(job.question_number),
                page_index=int(job.page_index),
                status="ok" if ok else "failed",
            )
        except Exception as e:  # pragma: no cover
            log_event(
                logger,
                "review_cards_worker_error",
                level="error",
                request_id=None,
                error_type=e.__class__.__name__,
                error=str(e),
            )
            logger.exception("Review cards worker error: %s", e)
            time.sleep(1)

    log_event(logger, "review_cards_worker_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
