"""
Facts worker process: extract derived question facts into Postgres tables.

Run:
  source .venv/bin/activate
  export PYTHONPATH=/path/to/project
  export REDIS_URL=redis://localhost:6379/0
  export REQUIRE_REDIS=1
  python3 -m homework_agent.workers.facts_worker
"""

from __future__ import annotations

import logging
import os
import signal
import time
from datetime import datetime
from typing import Any, Dict, Optional

from homework_agent.services.facts_extractor import extract_facts_from_grade_result
from homework_agent.services.facts_queue import FactsJob, get_redis_client, queue_key
from homework_agent.utils.taxonomy import taxonomy_version
from homework_agent.utils.logging_setup import setup_file_logging, silence_noisy_loggers
from homework_agent.utils.observability import log_event
from homework_agent.utils.settings import get_settings
from homework_agent.utils.supabase_client import (
    get_worker_storage_client,
)

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


def _safe_table(name: str):
    return get_worker_storage_client().client.table(name)


def _lock_key(submission_id: str) -> str:
    prefix = os.getenv("CACHE_PREFIX", "")
    return f"{prefix}lock:facts_extraction:{submission_id}"


def _acquire_lock(client, *, submission_id: str, ttl_seconds: int) -> Optional[str]:
    token = f"tok_{int(time.time() * 1000)}"
    ok = client.set(_lock_key(submission_id), token, nx=True, ex=int(ttl_seconds))
    return token if ok else None


def _release_lock(client, *, submission_id: str, token: str) -> None:
    # Best-effort: avoid deleting someone else's lock.
    key = _lock_key(submission_id)
    try:
        cur = client.get(key)
        cur_s = cur.decode("utf-8") if isinstance(cur, (bytes, bytearray)) else str(cur)
        if cur_s == token:
            client.delete(key)
    except Exception:
        return


def _load_submission(*, user_id: str, submission_id: str) -> Optional[Dict[str, Any]]:
    try:
        resp = (
            _safe_table("submissions")
            .select("submission_id,user_id,profile_id,subject,created_at,grade_result")
            .eq("submission_id", str(submission_id))
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None)
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0] if isinstance(rows[0], dict) else {}
        return row if isinstance(row, dict) else None
    except Exception:
        return None


def _upsert_rows(*, table: str, rows: list[dict], on_conflict: str) -> None:
    if not rows:
        return
    _safe_table(table).upsert(rows, on_conflict=on_conflict).execute()


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO)
    )
    silence_noisy_loggers()
    if getattr(settings, "log_to_file", True):
        level = getattr(logging, settings.log_level.upper(), logging.INFO)
        setup_file_logging(
            log_file_path="logs/facts_worker.log",
            level=level,
            logger_names=["", "homework_agent"],
        )

    client = get_redis_client()
    if client is None:
        logger.error("Redis unavailable; cannot start facts worker.")
        return 2

    qkey = queue_key()
    ttl_seconds = int(getattr(settings, "facts_lock_ttl_seconds", 600))
    stopper = _Stopper()
    _install_signal_handlers(stopper)

    log_event(logger, "facts_worker_started", queue=qkey)
    while not stopper.stop:
        try:
            item = client.brpop(qkey, timeout=2)
            if not item:
                continue
            _, raw = item
            job = FactsJob.from_json(
                raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            )
            if not job.submission_id or not job.user_id:
                continue

            token = _acquire_lock(
                client, submission_id=job.submission_id, ttl_seconds=ttl_seconds
            )
            if not token:
                log_event(
                    logger,
                    "facts_job_skipped_locked",
                    request_id=job.request_id,
                    session_id=job.session_id,
                    submission_id=job.submission_id,
                )
                continue

            started = time.monotonic()
            try:
                row = _load_submission(
                    user_id=job.user_id, submission_id=job.submission_id
                )
                if not row:
                    log_event(
                        logger,
                        "facts_job_failed",
                        level="warning",
                        request_id=job.request_id,
                        session_id=job.session_id,
                        submission_id=job.submission_id,
                        error="submission_not_found",
                        error_type="NotFound",
                    )
                    continue
                facts = extract_facts_from_grade_result(
                    user_id=job.user_id,
                    submission_id=job.submission_id,
                    created_at=row.get("created_at"),
                    subject=row.get("subject"),
                    grade_result=row.get("grade_result") or {},
                    taxonomy_version=taxonomy_version() or None,
                )
                profile_id = str(row.get("profile_id") or "").strip() or None
                if profile_id:
                    for a in facts.question_attempts:
                        if isinstance(a, dict):
                            a["profile_id"] = profile_id
                    for st in facts.question_steps:
                        if isinstance(st, dict):
                            st["profile_id"] = profile_id
                _upsert_rows(
                    table="question_attempts",
                    rows=facts.question_attempts,
                    on_conflict="user_id,submission_id,item_id",
                )
                _upsert_rows(
                    table="question_steps",
                    rows=facts.question_steps,
                    on_conflict="user_id,submission_id,item_id,step_index",
                )
                log_event(
                    logger,
                    "facts_job_done",
                    request_id=job.request_id,
                    session_id=job.session_id,
                    submission_id=job.submission_id,
                    attempts=len(facts.question_attempts),
                    steps=len(facts.question_steps),
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
            except Exception as e:
                log_event(
                    logger,
                    "facts_job_error",
                    level="error",
                    request_id=job.request_id,
                    session_id=job.session_id,
                    submission_id=job.submission_id,
                    error_type=e.__class__.__name__,
                    error=str(e),
                )
                logger.exception("Facts worker error: %s", e)
                time.sleep(1)
            finally:
                _release_lock(client, submission_id=job.submission_id, token=token)

        except Exception as e:  # pragma: no cover
            log_event(
                logger,
                "facts_worker_loop_error",
                level="error",
                error_type=e.__class__.__name__,
                error=str(e),
            )
            logger.exception("Facts worker loop error: %s", e)
            time.sleep(1)

    log_event(logger, "facts_worker_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
