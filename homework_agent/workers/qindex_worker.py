"""
QIndex worker process.

Run:
  source .venv/bin/activate
  export PYTHONPATH=/path/to/project
  python -m homework_agent.workers.qindex_worker

Requires:
  - REDIS_URL configured
  - redis python package installed
  - BAIDU_OCR_* configured if you want bbox/slice generation
"""

from __future__ import annotations

import logging
import signal
import time
from typing import Any

from homework_agent.utils.settings import get_settings
from homework_agent.utils.logging_setup import setup_file_logging, silence_noisy_loggers
from homework_agent.services.qindex_queue import (
    get_redis_client,
    queue_key,
    QIndexJob,
    store_qindex_result,
)
from homework_agent.utils.observability import log_event

# Keep the qindex builder in a stable shared module (avoid import path drift).
from homework_agent.core.qindex import build_question_index_for_pages  # noqa: E402
from homework_agent.api.session import get_question_bank  # noqa: E402
from homework_agent.core.slice_policy import pick_question_numbers_for_slices  # noqa: E402
from homework_agent.utils.submission_store import resolve_submission_for_session, persist_qindex_slices  # noqa: E402

logger = logging.getLogger(__name__)


class _Stopper:
    stop = False


def _install_signal_handlers(stopper: _Stopper) -> None:
    def _handle(signum, frame):  # noqa: ARG001
        stopper.stop = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def main() -> int:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    silence_noisy_loggers()

    # Also write worker logs to file by default (same opt-out flag as backend).
    if getattr(settings, "log_to_file", True):
        level = getattr(logging, settings.log_level.upper(), logging.INFO)
        setup_file_logging(log_file_path="logs/qindex_worker.log", level=level, logger_names=["", "homework_agent"])

    client = get_redis_client()
    if client is None:
        logger.error("REDIS_URL not configured or redis unavailable; cannot start qindex worker.")
        return 2

    stopper = _Stopper()
    _install_signal_handlers(stopper)

    ttl_seconds = 24 * 3600
    try:
        # Keep TTL consistent with API session TTL where possible.
        ttl_seconds = int(settings.slice_ttl_seconds) if settings.slice_ttl_seconds else ttl_seconds
    except Exception:
        ttl_seconds = 24 * 3600

    qkey = queue_key()
    log_event(logger, "qindex_worker_started", queue=qkey)

    while not stopper.stop:
        try:
            item = client.brpop(qkey, timeout=2)
            if not item:
                continue
            _, raw = item
            job = QIndexJob.from_json(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw))
            if not job.session_id or not job.page_urls:
                continue

            bank = get_question_bank(job.session_id) or {}
            allow = job.question_numbers or pick_question_numbers_for_slices(bank)
            log_event(
                logger,
                "qindex_job_start",
                session_id=job.session_id,
                pages=len(job.page_urls),
                questions=len(allow or []),
            )
            index: dict[str, Any] = build_question_index_for_pages(
                job.page_urls,
                question_numbers=allow,
                session_id=job.session_id,
            )
            store_qindex_result(job.session_id, index, ttl_seconds=ttl_seconds)
            # Best-effort: persist per-question slice refs to Postgres (7d TTL) for robustness.
            try:
                sub = resolve_submission_for_session(job.session_id) or {}
                sid = str(sub.get("submission_id") or "").strip()
                uid = str(sub.get("user_id") or "").strip()
                if sid and uid:
                    persist_qindex_slices(user_id=uid, submission_id=sid, session_id=job.session_id, qindex=index)
            except Exception as e:
                log_event(
                    logger,
                    "qindex_slices_persist_failed",
                    level="warning",
                    session_id=job.session_id,
                    error_type=e.__class__.__name__,
                    error=str(e),
                )

            log_event(
                logger,
                "qindex_job_done",
                session_id=job.session_id,
                questions=len(index.get("questions") or {}),
                warnings=index.get("warnings") or [],
            )

        except Exception as e:  # pragma: no cover
            log_event(
                logger,
                "qindex_worker_error",
                level="error",
                error_type=e.__class__.__name__,
                error=str(e),
            )
            logger.exception("QIndex worker error: %s", e)
            time.sleep(1)

    log_event(logger, "qindex_worker_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
