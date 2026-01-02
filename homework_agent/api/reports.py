from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from homework_agent.utils.supabase_client import get_storage_client
from homework_agent.utils.user_context import require_user_id

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


@router.post("/reports", status_code=status.HTTP_202_ACCEPTED)
def create_report_job(
    req: CreateReportRequest,
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
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
            .insert({"user_id": user_id, "params": params})
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
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    try:
        resp = (
            _safe_table("report_jobs")
            .select("*")
            .eq("id", str(job_id))
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
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


@router.get("/reports/{report_id}")
def get_report(
    report_id: str,
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    try:
        resp = (
            _safe_table("reports")
            .select("*")
            # DB schema uses `reports.id` (uuid). Keep route param name `report_id` for compatibility.
            .eq("id", str(report_id))
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
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
    limit: int = Query(default=20, ge=1, le=50),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    try:
        resp = (
            _safe_table("reports")
            .select("*")
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
            .limit(int(limit))
            .execute()
        )
        rows = getattr(resp, "data", None)
        return {"items": rows if isinstance(rows, list) else []}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"failed to list reports: {e}",
        ) from e
