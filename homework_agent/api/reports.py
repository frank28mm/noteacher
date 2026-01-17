from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from homework_agent.utils.supabase_client import get_storage_client
from homework_agent.utils.user_context import require_user_id
from homework_agent.utils.profile_context import require_profile_id
from homework_agent.utils.settings import get_settings
from homework_agent.services.quota_service import can_use_report_coupon

logger = logging.getLogger(__name__)

router = APIRouter()


def _safe_table(name: str):
    storage = get_storage_client()
    return storage.client.table(name)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CreateReportRequest(BaseModel):
    window_days: int = Field(default=7, ge=1, le=90)
    subject: Optional[str] = None
    # Optional: generate report for a single submission (demo-friendly).
    # When set, the worker should ignore window_days and only use this submission_id.
    submission_id: Optional[str] = Field(default=None, min_length=1)


class ReportEligibilityResponse(BaseModel):
    eligible: bool
    # Demo UI expects these names.
    submission_count: int = Field(ge=0)
    required_count: int = Field(ge=1)
    # Extra fields for product gating (same-subject distinct days).
    distinct_days: int = Field(default=0, ge=0)
    required_days: int = Field(default=0, ge=0)
    subject: Optional[str] = None
    reason: Optional[str] = None
    progress_percent: Optional[int] = Field(default=None, ge=0, le=100)
    sample_submission_ids: List[str] = Field(default_factory=list)


def _parse_utc_day(s: str) -> Optional[str]:
    """
    Convert an ISO timestamp string to a UTC day key (YYYY-MM-DD).
    Accepts 'Z' suffix by normalizing to '+00:00' for Python 3.10.
    """
    raw = (s or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.date().isoformat()
    except Exception:
        return None


def _compute_eligibility(
    *,
    rows: List[Dict[str, Any]],
    required_count: int,
    required_days: int,
) -> Dict[str, Any]:
    submission_ids: List[str] = []
    days: Set[str] = set()
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sid = str(r.get("submission_id") or "").strip()
        if sid:
            submission_ids.append(sid)
        day = _parse_utc_day(str(r.get("created_at") or ""))
        if day:
            days.add(day)

    unique_submission_ids = list(dict.fromkeys([s for s in submission_ids if s]))
    submission_count = len(unique_submission_ids)
    distinct_days = len(days)
    eligible = submission_count >= int(required_count) and distinct_days >= int(
        required_days
    )
    reason: Optional[str] = None
    if not eligible:
        if submission_count < int(required_count):
            reason = "need_more_submissions"
        elif distinct_days < int(required_days):
            reason = "need_more_days"

    progress_percent: Optional[int] = None
    try:
        if int(required_count) > 0:
            progress_percent = int(
                max(0.0, min(1.0, float(submission_count) / float(required_count)))
                * 100.0
            )
    except Exception:
        progress_percent = None

    return {
        "eligible": bool(eligible),
        "submission_count": int(submission_count),
        "required_count": int(required_count),
        "distinct_days": int(distinct_days),
        "required_days": int(required_days),
        "reason": reason,
        "progress_percent": progress_percent,
        "sample_submission_ids": unique_submission_ids[:5],
    }


@router.post("/reports", status_code=status.HTTP_202_ACCEPTED)
def create_report_job(
    req: CreateReportRequest,
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    profile_id = require_profile_id(user_id=user_id, x_profile_id=x_profile_id)
    settings = get_settings()
    if str(getattr(settings, "auth_mode", "dev") or "dev").strip().lower() != "dev":
        if not can_use_report_coupon(user_id=user_id):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="quota_insufficient",
            )
    now = _utc_now()
    params: Dict[str, Any] = {}
    submission_id = str(req.submission_id or "").strip()
    if submission_id:
        params["mode"] = "submission"
        params["submission_id"] = submission_id
    else:
        since = now - timedelta(days=int(req.window_days))
        params.update(
            {
                "window_days": int(req.window_days),
                "since": since.isoformat(),
                "until": now.isoformat(),
            }
        )
    if req.subject:
        params["subject"] = str(req.subject).strip()

    try:
        resp = (
            _safe_table("report_jobs")
            .insert({"user_id": user_id, "profile_id": profile_id, "params": params})
            .execute()
        )
        rows = getattr(resp, "data", None)
        row = rows[0] if isinstance(rows, list) and rows else {}
        job_id = str(row.get("id") or "").strip()
        if not job_id:
            raise RuntimeError("report_jobs insert returned empty id")
        return {"job_id": job_id, "status": str(row.get("status") or "pending")}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"failed to create report job: {e}",
        ) from e


@router.get("/reports/jobs/{job_id}")
def get_report_job(
    job_id: str,
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    profile_id = require_profile_id(user_id=user_id, x_profile_id=x_profile_id)
    try:
        q = (
            _safe_table("report_jobs")
            .select("*")
            .eq("id", str(job_id))
            .eq("user_id", str(user_id))
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        resp = q.limit(1).execute()
        rows = getattr(resp, "data", None)
        if not isinstance(rows, list) or not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="job not found"
            )
        row = rows[0] if isinstance(rows[0], dict) else {}
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"failed to query report job: {e}",
        ) from e


@router.get("/reports/eligibility", response_model=ReportEligibilityResponse)
def get_report_eligibility(
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
    subject: Optional[str] = Query(default=None, min_length=1),
    mode: str = Query(default="demo"),
    min_submissions: Optional[int] = Query(default=None, ge=1, le=50),
    min_distinct_days: Optional[int] = Query(default=None, ge=0, le=365),
    window_days: int = Query(default=90, ge=1, le=365),
):
    """
    Eligibility endpoint for report gating.

    Notes:
    - Avoids using /mistakes to infer submission count (perfect submissions would be invisible).
    - `mode=demo` defaults to: required_count=3, required_days=0
    - `mode=periodic` defaults to: required_count=3, required_days=3 (same-subject)
    """
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    profile_id = require_profile_id(user_id=user_id, x_profile_id=x_profile_id)
    mode_norm = str(mode or "").strip().lower() or "demo"
    if mode_norm not in {"demo", "periodic"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid mode (allowed: demo|periodic)",
        )

    required_count = int(min_submissions) if min_submissions is not None else 3
    if mode_norm == "periodic":
        required_days = (
            int(min_distinct_days) if min_distinct_days is not None else 3
        )
    else:
        required_days = (
            int(min_distinct_days) if min_distinct_days is not None else 0
        )

    since = _utc_now() - timedelta(days=int(window_days))
    try:
        q = (
            _safe_table("submissions")
            .select("submission_id,created_at,subject")
            .eq("user_id", str(user_id))
            .gte("created_at", since.isoformat())
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        q = q.order("created_at", desc=True).limit(500)
        if subject:
            q = q.eq("subject", str(subject).strip())
        resp = q.execute()
        rows = getattr(resp, "data", None)
        rows = rows if isinstance(rows, list) else []
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"failed to query submissions for eligibility: {e}",
        ) from e

    computed = _compute_eligibility(
        rows=[r for r in rows if isinstance(r, dict)],
        required_count=required_count,
        required_days=required_days,
    )
    return ReportEligibilityResponse(
        **computed,
        subject=str(subject).strip() if subject else None,
    )


@router.get("/reports/{report_id}")
def get_report(
    report_id: str,
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    profile_id = require_profile_id(user_id=user_id, x_profile_id=x_profile_id)
    try:
        q = (
            _safe_table("reports")
            .select("*")
            # DB schema uses `reports.id` (uuid). Keep route param name `report_id` for compatibility.
            .eq("id", str(report_id))
            .eq("user_id", str(user_id))
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        resp = q.limit(1).execute()
        rows = getattr(resp, "data", None)
        if not isinstance(rows, list) or not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="report not found"
            )
        row = rows[0] if isinstance(rows[0], dict) else {}
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"failed to query report: {e}",
        ) from e


@router.get("/reports")
def list_reports(
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
    limit: int = Query(default=20, ge=1, le=50),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    profile_id = require_profile_id(user_id=user_id, x_profile_id=x_profile_id)
    try:
        q = _safe_table("reports").select("*").eq("user_id", str(user_id))
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        resp = q.order("created_at", desc=True).limit(int(limit)).execute()
        rows = getattr(resp, "data", None)
        return {"items": rows if isinstance(rows, list) else []}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"failed to list reports: {e}",
        ) from e
