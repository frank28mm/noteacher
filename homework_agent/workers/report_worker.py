"""
Report worker process: consume report_jobs from Postgres (Supabase) and generate reports.

Run:
  source .venv/bin/activate
  export PYTHONPATH=/path/to/project
  python3 -m homework_agent.workers.report_worker
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from homework_agent.services.report_features import compute_report_features
from homework_agent.services.llm import LLMClient, ReportResult
from homework_agent.utils.logging_setup import setup_file_logging, silence_noisy_loggers
from homework_agent.utils.observability import log_event
from homework_agent.utils.settings import get_settings
from homework_agent.utils.supabase_client import get_storage_client
from homework_agent.utils.taxonomy import taxonomy_version
from homework_agent.utils.prompt_manager import get_prompt_manager
from homework_agent.utils.env import load_project_dotenv
from jinja2 import Template
import json

logger = logging.getLogger(__name__)

REPORT_VERSION = "report_v1_features_only"


class _Stopper:
    stop = False


def _install_signal_handlers(stopper: _Stopper) -> None:
    def _handle(signum, frame):  # noqa: ARG001
        stopper.stop = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _safe_table(name: str):
    storage = get_storage_client()
    return storage.client.table(name)


def _load_pending_job() -> Optional[Dict[str, Any]]:
    try:
        resp = (
            _safe_table("report_jobs")
            .select("*")
            .eq("status", "pending")
            .order("created_at", desc=False)
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


def _lock_job(job_id: str) -> Optional[Dict[str, Any]]:
    now = _iso(_utc_now())
    who = f"{socket.gethostname()}:{os.getpid()}"
    try:
        resp = (
            _safe_table("report_jobs")
            .update(
                {
                    "status": "running",
                    "updated_at": now,
                    # Note: locked_at column missing in current DB schema
                }
            )
            .eq("id", str(job_id))
            .eq("status", "pending")
            # .select("*") removed due to lib incompatibility
            .execute()
        )
        rows = getattr(resp, "data", None)
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0] if isinstance(rows[0], dict) else {}
        return row if isinstance(row, dict) else None
    except Exception:
        return None


def _mark_job_failed(*, job_id: str, error: str) -> None:
    now = _iso(_utc_now())
    try:
        _safe_table("report_jobs").update(
            {"status": "failed", "error": str(error)[:2000], "updated_at": now}
        ).eq("id", str(job_id)).execute()
    except Exception:
        return


def _mark_job_done(*, job_id: str, report_id: str) -> None:
    now = _iso(_utc_now())
    try:
        _safe_table("report_jobs").update(
            {"status": "done", "report_id": str(report_id), "updated_at": now}
        ).eq("id", str(job_id)).execute()
    except Exception:
        return


def _load_attempts(
    *, user_id: str, since: str, until: str, subject: Optional[str]
) -> List[Dict[str, Any]]:
    q = (
        _safe_table("question_attempts")
        .select(
            "submission_id,item_id,question_number,created_at,subject,verdict,knowledge_tags,knowledge_tags_norm,question_type,difficulty,severity,warnings"
        )
        .eq("user_id", str(user_id))
        .gte("created_at", str(since))
        .lte("created_at", str(until))
        .order("created_at", desc=True)
        .limit(5000)
    )
    if subject:
        q = q.eq("subject", str(subject))
    resp = q.execute()
    rows = getattr(resp, "data", None)
    return rows if isinstance(rows, list) else []


def _load_steps(*, user_id: str, since: str, until: str, subject: Optional[str]) -> List[Dict[str, Any]]:
    q = (
        _safe_table("question_steps")
        .select(
            "submission_id,item_id,step_index,created_at,subject,verdict,severity,diagnosis_codes"
        )
        .eq("user_id", str(user_id))
        .gte("created_at", str(since))
        .lte("created_at", str(until))
        .order("created_at", desc=True)
        .limit(10000)
    )
    if subject:
        q = q.eq("subject", str(subject))
    resp = q.execute()
    rows = getattr(resp, "data", None)
    return rows if isinstance(rows, list) else []


def _load_exclusions(*, user_id: str) -> Set[Tuple[str, str]]:
    try:
        resp = (
            _safe_table("mistake_exclusions")
            .select("submission_id,item_id")
            .eq("user_id", str(user_id))
            .limit(5000)
            .execute()
        )
        rows = getattr(resp, "data", None)
        out: Set[Tuple[str, str]] = set()
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            sid = str(r.get("submission_id") or "").strip()
            iid = str(r.get("item_id") or "").strip()
            if sid and iid:
                out.add((sid, iid))
        return out
    except Exception:
        return set()


def _filter_excluded_attempts(
    attempts: List[Dict[str, Any]], exclusions: Set[Tuple[str, str]]
) -> List[Dict[str, Any]]:
    if not exclusions:
        return attempts
    out: List[Dict[str, Any]] = []
    for a in attempts:
        if not isinstance(a, dict):
            continue
        sid = str(a.get("submission_id") or "").strip()
        iid = str(a.get("item_id") or "").strip()
        if sid and iid and (sid, iid) in exclusions:
            continue
        out.append(a)
    return out


def _insert_report(
    *,
    user_id: str,
    params: Dict[str, Any],
    features: Dict[str, Any],
    narrative: Optional[ReportResult] = None,
) -> str:
    # Map to actual DB schema (columns: id, user_id, content, stats, title, created_at, etc.)
    row = {
        "user_id": str(user_id),
        # Store features in stats column
        "stats": features,
        # Store params for reference
        "used_submission_ids": features.get("submission_ids") or [],
        # Time window from params
        "period_from": params.get("since"),
        "period_to": params.get("until"),
    }
    if narrative:
        # Combine narrative_md into content
        row["content"] = narrative.narrative_md
        # Use summary_json.title for title field
        summary = narrative.summary_json or {}
        row["title"] = summary.get("title", "学情诊断报告")
        # Store summary_json in exclusions_snapshot (temporarily)
        row["exclusions_snapshot"] = summary
    else:
        row["title"] = "学情分析报告"
        row["content"] = json.dumps(features, ensure_ascii=False, indent=2)

    resp = _safe_table("reports").insert(row).execute()
    rows = getattr(resp, "data", None)
    r0 = rows[0] if isinstance(rows, list) and rows else {}
    # Actual DB uses 'id' not 'report_id'
    rid = str(r0.get("id") or "").strip()
    if not rid:
        raise RuntimeError("reports insert returned empty id")
    return rid


def _compute_window(params: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
    # Prefer explicit since/until from params; fallback to window_days.
    since = str(params.get("since") or "").strip()
    until = str(params.get("until") or "").strip()
    subject = str(params.get("subject") or "").strip() or None
    if since and until:
        return since, until, subject
    days = int(params.get("window_days") or 7)
    now = _utc_now()
    return _iso(now - timedelta(days=days)), _iso(now), subject


def main() -> int:
    load_project_dotenv()
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO)
    )
    silence_noisy_loggers()
    if getattr(settings, "log_to_file", True):
        level = getattr(logging, settings.log_level.upper(), logging.INFO)
        setup_file_logging(
            log_file_path="logs/report_worker.log",
            level=level,
            logger_names=["", "homework_agent"],
        )

    stopper = _Stopper()
    _install_signal_handlers(stopper)

    log_event(logger, "report_worker_started")
    while not stopper.stop:
        try:
            job = _load_pending_job()
            if not job:
                time.sleep(1)
                continue
            job_id = str(job.get("id") or "").strip()
            user_id = str(job.get("user_id") or "").strip()
            params = job.get("params") if isinstance(job.get("params"), dict) else {}
            if not job_id or not user_id:
                time.sleep(0.5)
                continue

            locked = _lock_job(job_id)
            if not locked:
                continue

            started = time.monotonic()
            try:
                since, until, subject = _compute_window(params)
                attempts = _load_attempts(user_id=user_id, since=since, until=until, subject=subject)
                steps = _load_steps(user_id=user_id, since=since, until=until, subject=subject)
                exclusions = _load_exclusions(user_id=user_id)
                attempts = _filter_excluded_attempts(attempts, exclusions)
                # For steps, exclusions only apply to wrong attempts; we keep steps as-is for now (MVP).

                window = {"since": since, "until": until, "subject": subject}
                features = compute_report_features(
                    user_id=user_id,
                    attempts=attempts,
                    steps=steps,
                    window=window,
                    taxonomy_version=taxonomy_version() or None,
                    classifier_version=None,
                )
                
                # Narrative Layer
                report_narrative = None
                try:
                    pm = get_prompt_manager()
                    # We access _load directly or use a better public access if available. 
                    # Assuming we extend prompt_manager later, but for now _load works.
                    p_data = pm._load("report_analyst.yaml")
                    system_tmpl = p_data.get("system_template")
                    user_tmpl = p_data.get("user_template")
                    
                    if system_tmpl and user_tmpl:
                        user_prompt = Template(user_tmpl).render(
                            features_json=json.dumps(features, ensure_ascii=False, indent=2)
                        )
                        # Instantiate LLMClient just-in-time or hoist it out. Hoist is better but this is safe.
                        llm = LLMClient()
                        report_narrative = llm.generate_report(
                            system_prompt=system_tmpl,
                            user_prompt=user_prompt
                        )
                        log_event(logger, "report_narrative_generated", user_id=user_id)
                except Exception as nl_err:
                    logger.error(f"Narrative generation failed: {nl_err}")
                    log_event(logger, "report_narrative_failed", error=str(nl_err))
                
                report_id = _insert_report(
                    user_id=user_id, 
                    params=params, 
                    features=features,
                    narrative=report_narrative
                )
                _mark_job_done(job_id=job_id, report_id=report_id)
                log_event(
                    logger,
                    "report_job_done",
                    job_id=job_id,
                    report_id=report_id,
                    user_id=user_id,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
            except Exception as e:
                _mark_job_failed(job_id=job_id, error=str(e))
                log_event(
                    logger,
                    "report_job_failed",
                    level="warning",
                    job_id=job_id,
                    user_id=user_id,
                    error_type=e.__class__.__name__,
                    error=str(e),
                )
        except Exception as e:  # pragma: no cover
            log_event(
                logger,
                "report_worker_loop_error",
                level="error",
                error_type=e.__class__.__name__,
                error=str(e),
            )
            logger.exception("Report worker loop error: %s", e)
            time.sleep(1)

    log_event(logger, "report_worker_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

