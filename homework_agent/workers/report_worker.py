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
from homework_agent.services.facts_extractor import extract_facts_from_grade_result
from homework_agent.services.quota_service import (
    bt_from_usage,
    can_use_report_coupon,
    consume_report_coupon_and_reserve,
)
from homework_agent.utils.logging_setup import setup_file_logging, silence_noisy_loggers
from homework_agent.utils.observability import log_event
from homework_agent.utils.settings import get_settings
from homework_agent.utils.supabase_client import (
    get_worker_storage_client,
)
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
    return get_worker_storage_client().client.table(name)


def _load_pending_job() -> Optional[Dict[str, Any]]:
    try:
        resp = (
            _safe_table("report_jobs")
            .select("*")
            .in_("status", ["queued", "pending"])
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
        attempt = 0
        try:
            resp0 = (
                _safe_table("report_jobs")
                .select("attempt_count")
                .eq("id", str(job_id))
                .limit(1)
                .execute()
            )
            rows0 = getattr(resp0, "data", None)
            row0 = rows0[0] if isinstance(rows0, list) and rows0 else {}
            attempt = int(row0.get("attempt_count") or 0) if isinstance(row0, dict) else 0
        except Exception:
            attempt = 0
        payload = {
            "status": "running",
            "updated_at": now,
            "locked_at": now,
            "locked_by": who,
            "attempt_count": attempt + 1,
        }
        resp = (
            _safe_table("report_jobs")
            .update(payload)
            .eq("id", str(job_id))
            .in_("status", ["queued", "pending"])
            .execute()
        )
        rows = getattr(resp, "data", None)
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0] if isinstance(rows[0], dict) else {}
        return row if isinstance(row, dict) else None
    except Exception:
        # Backward-compatible fallback if lock columns don't exist yet.
        try:
            resp2 = (
                _safe_table("report_jobs")
                .update({"status": "running", "updated_at": now})
                .eq("id", str(job_id))
                .in_("status", ["queued", "pending"])
                .execute()
            )
            rows2 = getattr(resp2, "data", None)
            if not isinstance(rows2, list) or not rows2:
                return None
            row2 = rows2[0] if isinstance(rows2[0], dict) else {}
            return row2 if isinstance(row2, dict) else None
        except Exception:
            return None


def _mark_job_failed(*, job_id: str, error: str) -> None:
    now = _iso(_utc_now())
    try:
        payload = {
            "status": "failed",
            "error": str(error)[:2000],
            "last_error": str(error)[:2000],
            "updated_at": now,
        }
        _safe_table("report_jobs").update(payload).eq("id", str(job_id)).execute()
    except Exception:
        try:
            _safe_table("report_jobs").update(
                {"status": "failed", "error": str(error)[:2000], "updated_at": now}
            ).eq("id", str(job_id)).execute()
        except Exception:
            return


def _mark_job_done(*, job_id: str, report_id: str) -> None:
    now = _iso(_utc_now())
    try:
        payload = {"status": "done", "report_id": str(report_id), "updated_at": now}
        _safe_table("report_jobs").update(payload).eq("id", str(job_id)).execute()
    except Exception:
        try:
            _safe_table("report_jobs").update({"status": "done", "updated_at": now}).eq(
                "id", str(job_id)
            ).execute()
        except Exception:
            return


def _load_attempts(
    *,
    user_id: str,
    profile_id: Optional[str],
    since: str,
    until: str,
    subject: Optional[str],
) -> List[Dict[str, Any]]:
    try:
        q = (
            _safe_table("question_attempts")
            .select(
                "submission_id,item_id,question_number,created_at,subject,verdict,knowledge_tags,knowledge_tags_norm,question_type,difficulty,severity,warnings,question_raw"
            )
            .eq("user_id", str(user_id))
            .gte("created_at", str(since))
            .lte("created_at", str(until))
            .order("created_at", desc=True)
            .limit(5000)
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        if subject:
            q = q.eq("subject", str(subject))
        resp = q.execute()
        rows = getattr(resp, "data", None)
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _load_attempts_for_submission(
    *,
    user_id: str,
    profile_id: Optional[str],
    submission_id: str,
    subject: Optional[str],
) -> List[Dict[str, Any]]:
    try:
        q = (
            _safe_table("question_attempts")
            .select(
                "submission_id,item_id,question_number,created_at,subject,verdict,knowledge_tags,knowledge_tags_norm,question_type,difficulty,severity,warnings,question_raw"
            )
            .eq("user_id", str(user_id))
            .eq("submission_id", str(submission_id))
            .order("created_at", desc=True)
            .limit(5000)
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        if subject:
            q = q.eq("subject", str(subject))
        resp = q.execute()
        rows = getattr(resp, "data", None)
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _load_steps(
    *,
    user_id: str,
    profile_id: Optional[str],
    since: str,
    until: str,
    subject: Optional[str],
) -> List[Dict[str, Any]]:
    try:
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
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        if subject:
            q = q.eq("subject", str(subject))
        resp = q.execute()
        rows = getattr(resp, "data", None)
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _load_steps_for_submission(
    *,
    user_id: str,
    profile_id: Optional[str],
    submission_id: str,
    subject: Optional[str],
) -> List[Dict[str, Any]]:
    try:
        q = (
            _safe_table("question_steps")
            .select(
                "submission_id,item_id,step_index,created_at,subject,verdict,severity,diagnosis_codes"
            )
            .eq("user_id", str(user_id))
            .eq("submission_id", str(submission_id))
            .order("created_at", desc=True)
            .limit(10000)
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        if subject:
            q = q.eq("subject", str(subject))
        resp = q.execute()
        rows = getattr(resp, "data", None)
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _fallback_extract_from_submissions(
    *,
    user_id: str,
    profile_id: Optional[str],
    since: str,
    until: str,
    subject: Optional[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Fallback path when derived facts tables are missing/empty:
    load submissions within the window and re-extract facts in-process.
    """
    q = (
        _safe_table("submissions")
        .select("submission_id,user_id,subject,created_at,grade_result")
        .eq("user_id", str(user_id))
        .gte("created_at", str(since))
        .lte("created_at", str(until))
        .order("created_at", desc=True)
        .limit(2000)
    )
    if profile_id:
        q = q.eq("profile_id", str(profile_id))
    if subject:
        q = q.eq("subject", str(subject))
    resp = q.execute()
    rows = getattr(resp, "data", None)
    rows = rows if isinstance(rows, list) else []

    all_attempts: List[Dict[str, Any]] = []
    all_steps: List[Dict[str, Any]] = []
    tax_ver = taxonomy_version() or None
    for r in rows:
        if not isinstance(r, dict):
            continue
        sid = str(r.get("submission_id") or "").strip()
        uid = str(r.get("user_id") or "").strip()
        if not sid or not uid:
            continue
        facts = extract_facts_from_grade_result(
            user_id=uid,
            submission_id=sid,
            created_at=r.get("created_at"),
            subject=r.get("subject"),
            grade_result=r.get("grade_result") or {},
            taxonomy_version=tax_ver,
        )
        all_attempts.extend(facts.question_attempts)
        all_steps.extend(facts.question_steps)
    return all_attempts, all_steps


def _load_submission_meta(
    *, user_id: str, profile_id: Optional[str], submission_id: str
) -> Tuple[Optional[str], Optional[str]]:
    """
    Return (created_at_iso, subject) for a submission, if available.
    """
    try:
        q = (
            _safe_table("submissions")
            .select("submission_id,created_at,subject")
            .eq("user_id", str(user_id))
            .eq("submission_id", str(submission_id))
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        resp = q.limit(1).execute()
        rows = getattr(resp, "data", None)
        row = (
            rows[0]
            if isinstance(rows, list) and rows and isinstance(rows[0], dict)
            else {}
        )
        created_at = str(row.get("created_at") or "").strip() or None
        subject = str(row.get("subject") or "").strip() or None
        return created_at, subject
    except Exception:
        return None, None


def _fallback_extract_from_submission(
    *, user_id: str, profile_id: Optional[str], submission_id: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Fallback path: load a single submission and re-extract facts in-process.
    """
    q = (
        _safe_table("submissions")
        .select("submission_id,user_id,subject,created_at,grade_result")
        .eq("user_id", str(user_id))
        .eq("submission_id", str(submission_id))
    )
    if profile_id:
        q = q.eq("profile_id", str(profile_id))
    q = q.limit(1)
    resp = q.execute()
    rows = getattr(resp, "data", None)
    row = (
        rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    )
    if not row:
        return [], []

    sid = str(row.get("submission_id") or "").strip()
    uid = str(row.get("user_id") or "").strip()
    if not sid or not uid:
        return [], []
    facts = extract_facts_from_grade_result(
        user_id=uid,
        submission_id=sid,
        created_at=row.get("created_at"),
        subject=row.get("subject"),
        grade_result=row.get("grade_result") or {},
        taxonomy_version=taxonomy_version() or None,
    )
    return facts.question_attempts, facts.question_steps


def _load_exclusions(*, user_id: str, profile_id: Optional[str]) -> Set[Tuple[str, str]]:
    try:
        q = (
            _safe_table("mistake_exclusions")
            .select("submission_id,item_id")
            .eq("user_id", str(user_id))
            .limit(5000)
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        resp = q.execute()
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
    profile_id: Optional[str],
    report_job_id: str,
    params: Dict[str, Any],
    features: Dict[str, Any],
    narrative: Optional[ReportResult] = None,
) -> str:
    def _to_date(v: Any) -> Optional[str]:
        s = str(v or "").strip()
        if not s:
            return None
        if "T" in s:
            s = s.split("T", 1)[0]
        return s[:10] if len(s) >= 10 else None

    # Map to actual DB schema (columns: id, user_id, content, stats, title, created_at, etc.)
    row = {
        "user_id": str(user_id),
        "profile_id": (str(profile_id).strip() if profile_id else None),
        "report_job_id": str(report_job_id),
        # Store features in stats column
        "stats": features,
        # Store params for reference
        "used_submission_ids": features.get("submission_ids") or [],
        # Time window from params
        "period_from": _to_date(params.get("since")),
        "period_to": _to_date(params.get("until")),
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
            profile_id = str(job.get("profile_id") or "").strip() or None
            params = job.get("params") if isinstance(job.get("params"), dict) else {}
            if not job_id or not user_id:
                time.sleep(0.5)
                continue

            locked = _lock_job(job_id)
            if not locked:
                continue

            started = time.monotonic()
            try:
                if str(getattr(settings, "auth_mode", "dev") or "dev").strip().lower() != "dev":
                    if not can_use_report_coupon(user_id=user_id):
                        _mark_job_failed(job_id=job_id, error="quota_insufficient")
                        log_event(
                            logger,
                            "report_job_quota_insufficient",
                            level="warning",
                            job_id=job_id,
                            user_id=user_id,
                        )
                        continue
                effective_params = dict(params)
                submission_id = str(effective_params.get("submission_id") or "").strip()
                subject = str(effective_params.get("subject") or "").strip() or None
                if submission_id:
                    created_at, subj2 = _load_submission_meta(
                        user_id=user_id, profile_id=profile_id, submission_id=submission_id
                    )
                    if not subject and subj2:
                        subject = subj2
                    # Provide a stable window for downstream features/report persistence.
                    if created_at:
                        effective_params.setdefault("since", created_at)
                        effective_params.setdefault("until", created_at)

                    attempts = _load_attempts_for_submission(
                        user_id=user_id,
                        profile_id=profile_id,
                        submission_id=submission_id,
                        subject=subject,
                    )
                    steps = _load_steps_for_submission(
                        user_id=user_id,
                        profile_id=profile_id,
                        submission_id=submission_id,
                        subject=subject,
                    )
                    if not attempts and not steps:
                        attempts, steps = _fallback_extract_from_submission(
                            user_id=user_id, profile_id=profile_id, submission_id=submission_id
                        )
                        log_event(
                            logger,
                            "report_worker_fallback_extract_from_submission",
                            job_id=job_id,
                            user_id=user_id,
                            submission_id=submission_id,
                            attempts=len(attempts),
                            steps=len(steps),
                        )
                    window = {
                        "mode": "submission",
                        "submission_id": submission_id,
                        "subject": subject,
                    }
                else:
                    since, until, subject = _compute_window(effective_params)
                    attempts = _load_attempts(
                        user_id=user_id,
                        profile_id=profile_id,
                        since=since,
                        until=until,
                        subject=subject,
                    )
                    steps = _load_steps(
                        user_id=user_id,
                        profile_id=profile_id,
                        since=since,
                        until=until,
                        subject=subject,
                    )
                    if not attempts and not steps:
                        attempts, steps = _fallback_extract_from_submissions(
                            user_id=user_id,
                            profile_id=profile_id,
                            since=since,
                            until=until,
                            subject=subject,
                        )
                        log_event(
                            logger,
                            "report_worker_fallback_extract_from_submissions",
                            job_id=job_id,
                            user_id=user_id,
                            attempts=len(attempts),
                            steps=len(steps),
                        )
                    window = {"since": since, "until": until, "subject": subject}
                exclusions = _load_exclusions(user_id=user_id, profile_id=profile_id)
                attempts = _filter_excluded_attempts(attempts, exclusions)
                # For steps, exclusions only apply to wrong attempts; we keep steps as-is for now (MVP).

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
                report_usage: Optional[Dict[str, Any]] = None
                report_model: Optional[str] = None
                report_response_id: Optional[str] = None
                if bool(getattr(settings, "report_narrative_enabled", False)):
                    try:
                        pm = get_prompt_manager()
                        p_data = pm._load("report_analyst.yaml")
                        system_tmpl = p_data.get("system_template")
                        user_tmpl = p_data.get("user_template")

                        if system_tmpl and user_tmpl:
                            user_prompt = Template(user_tmpl).render(
                                features_json=json.dumps(
                                    features, ensure_ascii=False, indent=2
                                )
                            )
                            llm = LLMClient()
                            report_narrative = llm.generate_report(
                                system_prompt=system_tmpl, user_prompt=user_prompt
                            )
                            report_usage = llm.last_usage if isinstance(llm.last_usage, dict) else None
                            report_response_id = llm.last_response_id
                            report_model = str(
                                getattr(settings, "ark_report_model", None) or llm.ark_model
                            ) or None
                            log_event(
                                logger,
                                "report_narrative_generated",
                                user_id=user_id,
                                response_id=report_response_id,
                            )
                    except Exception as nl_err:
                        logger.error(f"Narrative generation failed: {nl_err}")
                        log_event(
                            logger,
                            "report_narrative_failed",
                            error=str(nl_err),
                            error_type=nl_err.__class__.__name__,
                        )
                else:
                    log_event(logger, "report_narrative_skipped", user_id=user_id)

                # WS-E: consume report coupon + report reserve (BT) once per report job.
                if str(getattr(settings, "auth_mode", "dev") or "dev").strip().lower() != "dev":
                    try:
                        bt_cost = 0
                        usage_payload: Optional[Dict[str, Any]] = None
                        if isinstance(report_usage, dict):
                            usage_payload = {
                                "prompt_tokens": int(report_usage.get("prompt_tokens") or 0),
                                "completion_tokens": int(report_usage.get("completion_tokens") or 0),
                                "total_tokens": int(report_usage.get("total_tokens") or 0),
                            }
                            bt_cost = bt_from_usage(
                                prompt_tokens=int(usage_payload.get("prompt_tokens") or 0),
                                completion_tokens=int(usage_payload.get("completion_tokens") or 0),
                            )
                        ok, err = consume_report_coupon_and_reserve(
                            user_id=user_id,
                            bt_cost=int(bt_cost),
                            idempotency_key=job_id,
                            request_id=job_id,
                            endpoint="/api/v1/reports",
                            stage="report",
                            model=report_model,
                            usage=usage_payload,
                        )
                        if not ok:
                            raise RuntimeError(str(err or "quota_charge_failed"))
                        log_event(
                            logger,
                            "report_quota_charged",
                            job_id=job_id,
                            user_id=user_id,
                            bt_cost=int(bt_cost),
                            response_id=report_response_id,
                        )
                    except Exception as e:
                        _mark_job_failed(job_id=job_id, error=str(e))
                        log_event(
                            logger,
                            "report_quota_charge_failed",
                            level="warning",
                            job_id=job_id,
                            user_id=user_id,
                            error_type=e.__class__.__name__,
                            error=str(e),
                        )
                        continue

                report_id = _insert_report(
                    user_id=user_id,
                    profile_id=profile_id,
                    report_job_id=job_id,
                    params=effective_params,
                    features=features,
                    narrative=report_narrative,
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
