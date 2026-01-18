from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from homework_agent.utils.observability import log_event
from homework_agent.utils.settings import get_settings
from homework_agent.utils.supabase_client import get_storage_client

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _safe_table(name: str):
    storage = get_storage_client()
    return storage.client.table(name)


def create_submission_on_upload(
    *,
    submission_id: str,
    user_id: str,
    profile_id: Optional[str] = None,
    session_id: Optional[str],
    request_id: Optional[str] = None,
    page_image_urls: List[str],
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
    size_bytes: Optional[int] = None,
) -> None:
    """
    Best-effort create a submission record (persistent "hard disk" source of truth).
    Never raises (should not break upload UX during early dev).
    """
    if not submission_id or not user_id:
        return
    try:
        now = _utc_now()
        record: Dict[str, Any] = {
            "submission_id": str(submission_id),
            "user_id": str(user_id),
            "profile_id": (str(profile_id).strip() if profile_id else None),
            "session_id": str(session_id) if session_id else None,
            "page_image_urls": [
                str(u).strip() for u in (page_image_urls or []) if str(u).strip()
            ],
            "proxy_page_image_urls": [],
            "grade_result": {},
            "warnings": [],
            "created_at": _iso(now),
            "last_active_at": _iso(now),
        }
        # Keep extra metadata in grade_result for now (schema stays minimal).
        extra: Dict[str, Any] = {}
        if filename:
            extra["filename"] = str(filename)
        if content_type:
            extra["content_type"] = str(content_type)
        if size_bytes is not None:
            extra["size_bytes"] = int(size_bytes)
        if extra:
            record["grade_result"] = {"upload": extra}

        _safe_table("submissions").upsert(record, on_conflict="submission_id").execute()
        log_event(
            logger,
            "submission_created",
            request_id=request_id,
            submission_id=submission_id,
            user_id=user_id,
            session_id=session_id,
            pages=len(record["page_image_urls"]),
        )
    except Exception as e:
        try:
            log_event(
                logger,
                "submission_create_failed",
                level="warning",
                request_id=request_id,
                submission_id=submission_id,
                user_id=user_id,
                session_id=session_id,
                error_type=e.__class__.__name__,
                error=str(e),
            )
        except Exception:
            pass


def touch_submission(
    *,
    user_id: str,
    profile_id: Optional[str] = None,
    submission_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """Best-effort update last_active_at (used by 180-day inactivity cleanup)."""
    if not user_id:
        return
    sid = (submission_id or "").strip()
    sess = (session_id or "").strip()
    if not (sid or sess):
        return
    try:
        now = _iso(_utc_now())
        q = _safe_table("submissions").update({"last_active_at": now})
        if sid:
            q = q.eq("submission_id", sid)
        if sess:
            q = q.eq("session_id", sess)
        q = q.eq("user_id", str(user_id))
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        q.execute()
    except Exception:
        return


def resolve_page_image_urls(
    *,
    user_id: str,
    profile_id: Optional[str] = None,
    submission_id: str,
    prefer_proxy: bool = True,
) -> List[str]:
    """Lookup page_image_urls for a submission (used by /grade when images are omitted)."""
    if not user_id or not submission_id:
        return []
    try:
        q = (
            _safe_table("submissions")
            .select("page_image_urls,proxy_page_image_urls")
            .eq("submission_id", str(submission_id))
            .eq("user_id", str(user_id))
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        resp = q.limit(1).execute()
        rows = getattr(resp, "data", None)
        if not isinstance(rows, list) or not rows:
            return []
        row = rows[0] if isinstance(rows[0], dict) else {}
        # Prefer proxy urls if present (stable lightweight copies).
        if bool(prefer_proxy):
            proxy = row.get("proxy_page_image_urls")
            if isinstance(proxy, list) and any(str(u).strip() for u in proxy):
                return [str(u).strip() for u in proxy if str(u).strip()]
        urls = row.get("page_image_urls")
        if isinstance(urls, list):
            return [str(u).strip() for u in urls if str(u).strip()]
        return []
    except Exception:
        return []


def resolve_submission_for_session(session_id: str) -> Optional[Dict[str, str]]:
    """
    Best-effort lookup: {submission_id,user_id} for a session_id.
    Used by worker/chat to map runtime session -> durable submission.
    """
    sess = (session_id or "").strip()
    if not sess:
        return None
    try:
        resp = (
            _safe_table("submissions")
            .select("submission_id,user_id,profile_id")
            .eq("session_id", sess)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None)
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0] if isinstance(rows[0], dict) else {}
        sid = str(row.get("submission_id") or "").strip()
        uid = str(row.get("user_id") or "").strip()
        pid = str(row.get("profile_id") or "").strip()
        if not sid or not uid:
            return None
        out = {"submission_id": sid, "user_id": uid}
        if pid:
            out["profile_id"] = pid
        return out
    except Exception:
        return None


def update_submission_after_grade(
    *,
    user_id: str,
    submission_id: str,
    session_id: str,
    profile_id: Optional[str] = None,
    request_id: Optional[str] = None,
    subject: Optional[str],
    page_image_urls: Optional[List[str]],
    proxy_page_image_urls: Optional[List[str]],
    vision_raw_text: Optional[str],
    grade_result: Dict[str, Any],
    warnings: List[str],
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort persist grading outputs as long-term submission facts."""
    if not user_id or not submission_id:
        return
    try:
        # Best-effort repair (P0):
        # Enforce "blank => incorrect" consistently and mitigate a common OCR/LLM issue where
        # choice placeholders "（ ）" are misread as "（A）" and then treated as a student's answer.
        # This runs before persistence so list/detail UIs stay consistent without requiring a re-grade.
        try:
            questions = grade_result.get("questions") if isinstance(grade_result, dict) else None
            if (
                isinstance(questions, list)
                and vision_raw_text
                and str(vision_raw_text).strip()
                and subject
            ):
                from homework_agent.core.qbank_parser import build_question_bank_from_vision_raw_text
                from homework_agent.core.qbank_builder import normalize_questions as _normalize_questions_for_storage
                from homework_agent.models.schemas import Subject as SubjectEnum

                subj_raw = str(subject or "").strip().lower()
                subj = SubjectEnum.ENGLISH if subj_raw == "english" else SubjectEnum.MATH
                page_urls = page_image_urls if isinstance(page_image_urls, list) else []
                vision_qbank = build_question_bank_from_vision_raw_text(
                    session_id=str(session_id or ""),
                    subject=subj,
                    vision_raw_text=str(vision_raw_text),
                    page_image_urls=[str(u).strip() for u in page_urls if str(u).strip()],
                )
                vision_questions_map = (
                    vision_qbank.get("questions")
                    if isinstance(vision_qbank.get("questions"), dict)
                    else {}
                )

                # Enrich with OCR stems/options for heuristics, then normalize and apply back
                # only verdict/answer_state fields (avoid overwriting stored question_content).
                enriched: List[Dict[str, Any]] = []
                for q in questions:
                    if not isinstance(q, dict):
                        continue
                    cq = dict(q)
                    qn = str(cq.get("question_number") or "").strip()
                    vq = vision_questions_map.get(qn) if qn else None
                    if isinstance(vq, dict):
                        if vq.get("question_content"):
                            cq["question_content"] = vq.get("question_content")
                        if vq.get("options") is not None:
                            cq["options"] = vq.get("options")
                    # Some heuristics depend on a full stem+options text.
                    try:
                        from homework_agent.core.qbank_builder import _compose_question_text_full

                        cq["question_text"] = _compose_question_text_full(cq)
                    except Exception:
                        pass
                    enriched.append(cq)

                repaired_enriched = _normalize_questions_for_storage(enriched)
                repaired_map: Dict[str, Dict[str, Any]] = {}
                for it in repaired_enriched:
                    if not isinstance(it, dict):
                        continue
                    qn = str(it.get("question_number") or "").strip()
                    if qn:
                        repaired_map[qn] = it

                repaired_questions: List[Dict[str, Any]] = []
                for q in questions:
                    if not isinstance(q, dict):
                        continue
                    cq = dict(q)
                    qn = str(cq.get("question_number") or "").strip()
                    fixed = repaired_map.get(qn) if qn else None
                    if isinstance(fixed, dict):
                        for k in (
                            "verdict",
                            "answer_state",
                            "student_answer",
                            "answer_status",
                            "warnings",
                        ):
                            if k in fixed:
                                cq[k] = fixed.get(k)
                    repaired_questions.append(cq)

                # Recompute counters from repaired questions (avoid stale aggregates).
                wrong = 0
                uncertain = 0
                blank = 0
                for q in repaired_questions:
                    if not isinstance(q, dict):
                        continue
                    ans_state = str(q.get("answer_state") or "").strip().lower()
                    if ans_state == "blank":
                        blank += 1
                        continue
                    v = str(q.get("verdict") or "").strip().lower()
                    if v == "incorrect":
                        wrong += 1
                    elif v == "uncertain":
                        uncertain += 1

                grade_result = dict(grade_result or {})
                grade_result["questions"] = repaired_questions
                grade_result["total_items"] = int(len(repaired_questions))
                grade_result["wrong_count"] = int(wrong)
                grade_result["uncertain_count"] = int(uncertain)
                grade_result["blank_count"] = int(blank)
        except Exception:
            # best-effort only; never block persistence
            pass

        now = _utc_now()
        payload: Dict[str, Any] = {
            "session_id": str(session_id) if session_id else None,
            "subject": str(subject) if subject else None,
            "vision_raw_text": vision_raw_text,
            "grade_result": grade_result or {},
            "warnings": warnings or [],
            "last_active_at": _iso(now),
        }
        if profile_id:
            payload["profile_id"] = str(profile_id)
        if page_image_urls is not None:
            payload["page_image_urls"] = [
                str(u).strip() for u in (page_image_urls or []) if str(u).strip()
            ]
        if proxy_page_image_urls is not None:
            payload["proxy_page_image_urls"] = [
                str(u).strip() for u in (proxy_page_image_urls or []) if str(u).strip()
            ]
        if meta:
            # Keep provider/meta inside grade_result for now to avoid schema churn.
            payload["grade_result"] = dict(grade_result or {})
            payload["grade_result"]["_meta"] = meta

        _safe_table("submissions").upsert(
            {**payload, "submission_id": submission_id, "user_id": user_id},
            on_conflict="submission_id",
        ).execute()
        log_event(
            logger,
            "submission_graded",
            request_id=request_id,
            submission_id=submission_id,
            user_id=user_id,
            session_id=session_id,
        )
    except Exception as e:
        try:
            log_event(
                logger,
                "submission_grade_persist_failed",
                level="warning",
                request_id=request_id,
                submission_id=submission_id,
                user_id=user_id,
                session_id=session_id,
                error_type=e.__class__.__name__,
                error=str(e),
            )
        except Exception:
            pass


def persist_qindex_slices(
    *,
    user_id: str,
    profile_id: Optional[str] = None,
    submission_id: str,
    session_id: str,
    qindex: Dict[str, Any],
    request_id: Optional[str] = None,
) -> None:
    """
    Persist per-question qindex image refs to Postgres with TTL (24h by default).
    This allows chat to find slices even if Redis lost/restarted within the TTL window.
    """
    if not user_id or not submission_id or not session_id:
        return
    if not isinstance(qindex, dict):
        return
    qs = qindex.get("questions")
    if not isinstance(qs, dict) or not qs:
        return

    settings = get_settings()
    ttl_s = int(getattr(settings, "slice_ttl_seconds", 24 * 3600) or 24 * 3600)
    expires_at = _iso(_utc_now() + timedelta(seconds=ttl_s))

    try:
        rows: List[Dict[str, Any]] = []
        for qn, image_refs in qs.items():
            qn_s = str(qn).strip()
            if not qn_s:
                continue
            if not isinstance(image_refs, dict):
                continue
            rows.append(
                {
                    "user_id": str(user_id),
                    "profile_id": (str(profile_id).strip() if profile_id else None),
                    "submission_id": str(submission_id),
                    "session_id": str(session_id),
                    "question_number": qn_s,
                    "image_refs": image_refs,
                    "expires_at": expires_at,
                }
            )
        if not rows:
            return
        _safe_table("qindex_slices").upsert(
            rows, on_conflict="submission_id,question_number"
        ).execute()
        log_event(
            logger,
            "qindex_slices_persisted",
            request_id=request_id,
            submission_id=submission_id,
            session_id=session_id,
            questions=len(rows),
        )
    except Exception as e:
        try:
            log_event(
                logger,
                "qindex_slices_persist_failed",
                level="warning",
                request_id=request_id,
                submission_id=submission_id,
                session_id=session_id,
                error_type=e.__class__.__name__,
                error=str(e),
            )
        except Exception:
            pass
        return


def load_qindex_image_refs(
    *,
    user_id: str,
    profile_id: Optional[str] = None,
    session_id: str,
    question_number: str,
) -> Optional[Dict[str, Any]]:
    """Load per-question image_refs from Postgres (best-effort; ignores expiration enforcement for now)."""
    if not user_id or not session_id or not question_number:
        return None
    try:
        q = (
            _safe_table("qindex_slices")
            .select("image_refs,expires_at")
            .eq("user_id", str(user_id))
            .eq("session_id", str(session_id))
            .eq("question_number", str(question_number))
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        resp = q.limit(1).execute()
        rows = getattr(resp, "data", None)
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0] if isinstance(rows[0], dict) else {}
        # Enforce expiration (fail closed).
        exp = row.get("expires_at")
        if exp:
            try:
                exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if _utc_now() >= exp_dt.astimezone(timezone.utc):
                    return None
            except Exception:
                # If parsing fails, keep best-effort behavior.
                pass
        image_refs = row.get("image_refs")
        return image_refs if isinstance(image_refs, dict) else None
    except Exception:
        return None


def link_session_to_submission(
    *,
    user_id: str,
    submission_id: str,
    session_id: str,
    subject: Optional[str] = None,
) -> None:
    """
    Best-effort: attach a runtime session_id to a durable submission without overwriting grade_result.
    This enables chat to map session_id -> submission for last_active updates and slice lookup.
    """
    if not user_id or not submission_id or not session_id:
        return
    try:
        now = _iso(_utc_now())
        payload: Dict[str, Any] = {"session_id": str(session_id), "last_active_at": now}
        if subject:
            payload["subject"] = str(subject)
        (
            _safe_table("submissions")
            .update(payload)
            .eq("submission_id", str(submission_id))
            .eq("user_id", str(user_id))
            .execute()
        )
    except Exception:
        return
