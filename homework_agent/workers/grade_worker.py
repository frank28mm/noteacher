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

from homework_agent.utils.logging_setup import setup_file_logging, silence_noisy_loggers
from homework_agent.utils.settings import get_settings
from homework_agent.utils.observability import log_event
from homework_agent.models.schemas import GradeRequest
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
from homework_agent.api.session import get_question_bank
from homework_agent.utils.submission_store import update_submission_after_grade

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
                set_job_status(
                    job.job_id,
                    {
                        "status": "done",
                        "created_at": _iso_now(),
                        "request": req_obj,
                        "result": result.model_dump(),
                        "finished_at": _iso_now(),
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    },
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
