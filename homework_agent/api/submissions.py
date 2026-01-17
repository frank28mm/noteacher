from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from homework_agent.utils.supabase_client import get_storage_client
from homework_agent.utils.profile_context import (
    ensure_default_profile,
    require_profile_id,
    validate_profile_ownership,
)
from homework_agent.utils.user_context import require_user_id
from homework_agent.services.qindex_queue import enqueue_qindex_job

logger = logging.getLogger(__name__)

router = APIRouter()


def _safe_table(name: str):
    storage = get_storage_client()
    return storage.client.table(name)


def _parse_iso_utc_ts(value: str) -> Optional[str]:
    """
    Parse an ISO timestamp string and normalize to UTC ISO format for supabase filters.
    Returns None if invalid.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


def _load_qindex_slices_for_submission(
    *, user_id: str, profile_id: Optional[str], submission_id: str
) -> Dict[str, Dict[str, Any]]:
    """
    Load per-question qindex slice refs for a submission (best-effort).
    Returns: {question_number: image_refs}
    """
    uid = (user_id or "").strip()
    sid = (submission_id or "").strip()
    if not uid or not sid:
        return {}
    try:
        q = (
            _safe_table("qindex_slices")
            .select("question_number,image_refs,expires_at")
            .eq("user_id", uid)
            .eq("submission_id", sid)
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        resp = q.limit(500).execute()
        rows = getattr(resp, "data", None)
        if not isinstance(rows, list) or not rows:
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        now = datetime.now(timezone.utc)
        for r in rows:
            if not isinstance(r, dict):
                continue
            qn = str(r.get("question_number") or "").strip()
            qn = qn.replace("（", "(").replace("）", ")").replace(" ", "").rstrip(".．")
            if not qn:
                continue
            refs = r.get("image_refs")
            if not isinstance(refs, dict):
                continue
            exp = r.get("expires_at")
            if exp:
                try:
                    exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    if now >= exp_dt.astimezone(timezone.utc):
                        continue
                except Exception:
                    # If parsing fails, keep best-effort behavior.
                    pass
            out[qn] = refs
        return out
    except Exception:
        return {}


def _pick_first_slice_url(image_refs: Dict[str, Any], *, kind: str) -> Optional[str]:
    """Pick the first slice_image_url for a region kind (question/figure) from qindex image_refs."""
    if not isinstance(image_refs, dict):
        return None
    pages = image_refs.get("pages")
    if isinstance(pages, list):
        for p in pages:
            if not isinstance(p, dict):
                continue
            regions = p.get("regions")
            if not isinstance(regions, list):
                continue
            for r in regions:
                if not isinstance(r, dict):
                    continue
                if str(r.get("kind") or "").strip().lower() != str(kind).lower():
                    continue
                url = str(r.get("slice_image_url") or "").strip()
                if url:
                    return url
    return None


def _compose_question_text_full(q: Dict[str, Any]) -> Optional[str]:
    """
    Build a plain-text "full question text" for UI:
    - stem from question_content
    - append multiple-choice options when present
    """
    if not isinstance(q, dict):
        return None
    stem = str(q.get("question_content") or "").strip()
    options = q.get("options")
    opt_lines: List[str] = []
    if isinstance(options, dict):
        for key in ("A", "B", "C", "D", "E", "F"):
            val = options.get(key)
            if val is None:
                continue
            s = str(val).strip()
            if s:
                opt_lines.append(f"{key}. {s}")
        for key, val in options.items():
            k = str(key).strip()
            if k in {"A", "B", "C", "D", "E", "F"}:
                continue
            s = str(val).strip()
            if k and s:
                opt_lines.append(f"{k}. {s}")

    # Avoid duplicating options if stem already includes A./B. ...
    if opt_lines and stem:
        if any(mark in stem for mark in ("A.", "A、", "A:", "A：", "(A)", "（A）")):
            opt_lines = []

    full = stem
    if opt_lines:
        full = f"{stem}\n" if stem else ""
        full += "\n".join(opt_lines)
    full = full.strip()
    return full or None


def _normalize_question_key(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace(" ", "")
    s = s.rstrip(".．")
    return s


class SubmissionSummary(BaseModel):
    total_items: int = Field(default=0, ge=0)
    wrong_count: int = Field(default=0, ge=0)
    uncertain_count: int = Field(default=0, ge=0)
    blank_count: int = Field(default=0, ge=0)
    score_text: Optional[str] = None


class SubmissionItem(BaseModel):
    submission_id: str
    profile_id: Optional[str] = None
    created_at: str
    subject: Optional[str] = None
    total_pages: int = Field(default=0, ge=0)
    done_pages: int = Field(default=0, ge=0)
    session_id: Optional[str] = None
    summary: Optional[SubmissionSummary] = None


class ListSubmissionsResponse(BaseModel):
    items: List[SubmissionItem] = Field(default_factory=list)
    next_before: Optional[str] = None


class SubmissionDetailResponse(BaseModel):
    submission_id: str
    profile_id: Optional[str] = None
    created_at: str
    subject: Optional[str] = None
    total_pages: int = Field(default=0, ge=0)
    done_pages: int = Field(default=0, ge=0)
    session_id: Optional[str] = None
    page_image_urls: List[str] = Field(default_factory=list)
    vision_raw_text: Optional[str] = None
    question_cards: List[Dict[str, Any]] = Field(default_factory=list)
    page_summaries: List[Dict[str, Any]] = Field(default_factory=list)
    questions: List[Dict[str, Any]] = Field(default_factory=list)


def _compute_summary_from_grade_result(grade_result: Any) -> Optional[SubmissionSummary]:
    if not isinstance(grade_result, dict) or not grade_result:
        return None
    questions = grade_result.get("questions")
    if not isinstance(questions, list):
        questions = []
    total_items = len(questions)
    wrong = 0
    uncertain = 0
    blank = 0
    for q in questions:
        if not isinstance(q, dict):
            continue
        verdict = str(q.get("verdict") or "").strip().lower()
        answer_state = str(q.get("answer_state") or "").strip().lower()
        if answer_state == "blank":
            blank += 1
            continue
        if verdict == "incorrect":
            wrong += 1
        elif verdict == "uncertain":
            uncertain += 1
    try:
        # Prefer counters derived from questions[*] if available; stored aggregate fields may be stale.
        if total_items > 0:
            return SubmissionSummary(
                total_items=total_items,
                wrong_count=wrong,
                uncertain_count=uncertain,
                blank_count=blank,
                score_text=str(grade_result.get("score_text") or "").strip() or None,
            )
        return SubmissionSummary(
            total_items=int(grade_result.get("total_items") or total_items or 0),
            wrong_count=int(grade_result.get("wrong_count") or wrong or 0),
            uncertain_count=int(grade_result.get("uncertain_count") or uncertain or 0),
            blank_count=int(grade_result.get("blank_count") or blank or 0),
            score_text=str(grade_result.get("score_text") or "").strip() or None,
        )
    except Exception:
        return SubmissionSummary(
            total_items=total_items,
            wrong_count=wrong,
            uncertain_count=uncertain,
            blank_count=blank,
            score_text=None,
        )


@router.get("/submissions", response_model=ListSubmissionsResponse)
def list_submissions(
    subject: Optional[str] = Query(default=None, min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    before: Optional[str] = Query(
        default=None, description="ISO timestamp; return items with created_at < before"
    ),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
) -> ListSubmissionsResponse:
    """
    List durable submissions for Recent Activity / History.

    Source of truth: `submissions` table (do NOT infer from /mistakes).
    """
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    profile_id = require_profile_id(user_id=user_id, x_profile_id=x_profile_id)
    subj = (subject or "").strip().lower() or None
    before_iso = _parse_iso_utc_ts(before or "") if before else None
    if before and not before_iso:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid before timestamp (expect ISO 8601)",
        )

    try:
        q = _safe_table("submissions").select(
            "submission_id,profile_id,created_at,subject,session_id,page_image_urls,grade_result"
        )
        q = q.eq("user_id", str(user_id))
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        q = q.order("created_at", desc=True).limit(int(limit))
        if subj:
            q = q.eq("subject", subj)
        if before_iso:
            q = q.lt("created_at", before_iso)
        res = q.execute()
        rows = res.data or []
    except Exception as e:
        logger.exception("list_submissions failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to list submissions: {e.__class__.__name__}",
        )

    items: List[SubmissionItem] = []
    next_before: Optional[str] = None
    for r in rows:
        if not isinstance(r, dict):
            continue
        sid = str(r.get("submission_id") or "").strip()
        created_at = str(r.get("created_at") or "").strip()
        if not sid or not created_at:
            continue
        page_urls = r.get("page_image_urls")
        total_pages = len(page_urls) if isinstance(page_urls, list) else 0
        summary = _compute_summary_from_grade_result(r.get("grade_result"))
        # If grade_result exists, treat as done; otherwise keep done_pages=0.
        done_pages = total_pages if summary is not None else 0
        items.append(
            SubmissionItem(
                submission_id=sid,
                profile_id=(str(r.get("profile_id") or "").strip() or None),
                created_at=created_at,
                subject=(str(r.get("subject") or "").strip() or None),
                total_pages=total_pages,
                done_pages=done_pages,
                session_id=(str(r.get("session_id") or "").strip() or None),
                summary=summary,
            )
        )

    if items:
        next_before = items[-1].created_at

    return ListSubmissionsResponse(items=items, next_before=next_before)


@router.get("/submissions/{submission_id}", response_model=SubmissionDetailResponse)
def get_submission_detail(
    submission_id: str,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
) -> SubmissionDetailResponse:
    """
    Fetch a single submission snapshot for History Detail (Option B).
    Returns derived question_cards/page_summaries so the frontend can render without rebuilding a job.
    """
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    profile_id = require_profile_id(user_id=user_id, x_profile_id=x_profile_id)
    sid = (submission_id or "").strip()
    if not sid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="missing submission_id"
        )

    try:
        q = _safe_table("submissions").select(
            "submission_id,profile_id,created_at,subject,session_id,page_image_urls,vision_raw_text,grade_result,warnings"
        )
        q = q.eq("user_id", str(user_id)).eq("submission_id", sid)
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        resp = q.limit(1).execute()
        rows = getattr(resp, "data", None)
        row = (
            rows[0]
            if isinstance(rows, list) and rows and isinstance(rows[0], dict)
            else None
        )
    except Exception as e:
        logger.exception("get_submission_detail failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to load submission: {e.__class__.__name__}",
        )

    if not isinstance(row, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="submission not found"
        )

    page_image_urls = row.get("page_image_urls")
    page_image_urls = (
        [str(u).strip() for u in page_image_urls if str(u).strip()]
        if isinstance(page_image_urls, list)
        else []
    )
    total_pages = len(page_image_urls)

    grade_result = row.get("grade_result") if isinstance(row.get("grade_result"), dict) else {}
    questions = grade_result.get("questions") if isinstance(grade_result.get("questions"), list) else []
    qindex_slices = _load_qindex_slices_for_submission(user_id=str(user_id), profile_id=profile_id, submission_id=sid)
    vision_raw_text = str(row.get("vision_raw_text") or "").strip()

    # Best-effort: reconstruct question_text from stored vision_raw_text.
    # For user-facing UI, prefer OCR-grounded stems/options when available.
    vision_qbank: Dict[str, Any] = {}
    if vision_raw_text:
        try:
            from homework_agent.core.qbank_parser import build_question_bank_from_vision_raw_text
            from homework_agent.models.schemas import Subject

            subj_raw = str(row.get("subject") or "").strip().lower()
            subj = Subject.ENGLISH if subj_raw == "english" else Subject.MATH
            vision_qbank = build_question_bank_from_vision_raw_text(
                session_id=str(row.get("session_id") or ""),
                subject=subj,
                vision_raw_text=vision_raw_text,
                page_image_urls=page_image_urls,
            )
        except Exception:
            vision_qbank = {}
    vision_questions_map = (
        vision_qbank.get("questions") if isinstance(vision_qbank.get("questions"), dict) else {}
    )
    # If grade_result has no per-question payload (older records / partial runs),
    # fall back to OCR-derived questions so the UI can still display full stems.
    if (not questions) and isinstance(vision_questions_map, dict) and vision_questions_map:
        questions = [
            v for v in vision_questions_map.values() if isinstance(v, dict) and v.get("question_number")
        ]

    safe_questions: List[Dict[str, Any]] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        copy_q = dict(q)
        copy_q.pop("standard_answer", None)
        qn_raw = _normalize_question_key(copy_q.get("question_number"))
        vq = vision_questions_map.get(qn_raw) if qn_raw else None
        if isinstance(vq, dict):
            if vq.get("question_content"):
                copy_q["question_content"] = vq.get("question_content")
            if vq.get("options") is not None:
                copy_q["options"] = vq.get("options")
        copy_q["question_text"] = _compose_question_text_full(copy_q)

        # Canonicalize question item_id to align with UI card ids (p{page}:q:{question_number}).
        # This prevents inconsistent deep-linking between "questions" and "question_cards".
        try:
            from homework_agent.core.question_cards import make_card_item_id

            page_index_raw = copy_q.get("page_index")
            page_index_i = int(page_index_raw) if page_index_raw is not None else 0
        except Exception:
            page_index_i = 0
            make_card_item_id = None  # type: ignore[assignment]
        if make_card_item_id is not None:
            copy_q["item_id"] = make_card_item_id(
                page_index=page_index_i, question_number=copy_q.get("question_number")
            )

        qn = _normalize_question_key(copy_q.get("question_number"))
        if qn and qn in qindex_slices:
            refs = qindex_slices.get(qn) or {}
            if isinstance(refs, dict) and refs:
                copy_q["image_refs"] = refs
                copy_q["question_slice_image_url"] = _pick_first_slice_url(
                    refs, kind="question"
                )
                copy_q["figure_slice_image_url"] = _pick_first_slice_url(refs, kind="figure")
        safe_questions.append(copy_q)

    # Build derived question_cards from stored questions list (expects page_index; fallback to 0).
    from homework_agent.core.question_cards import (
        build_question_cards_from_questions_list,
        merge_question_cards,
        sort_question_cards,
    )

    cards_by_id: Dict[str, Dict[str, Any]] = {}
    page_summaries: List[Dict[str, Any]] = []
    max_page_index = -1
    pages_seen: Dict[int, List[Dict[str, Any]]] = {}
    for q in safe_questions:
        if not isinstance(q, dict):
            continue
        pi = q.get("page_index")
        try:
            pi_i = int(pi) if pi is not None else 0
        except Exception:
            pi_i = 0
        max_page_index = max(max_page_index, pi_i)
        pages_seen.setdefault(pi_i, []).append(q)

    for page_index, qs in sorted(pages_seen.items(), key=lambda x: x[0]):
        verdict_cards, blank_count = build_question_cards_from_questions_list(
            page_index=int(page_index),
            questions=qs,
            card_state="verdict_ready",
        )
        cards_by_id = merge_question_cards(cards_by_id, verdict_cards)
        wrong_count = 0
        uncertain_count = 0
        for c in verdict_cards:
            if not isinstance(c, dict):
                continue
            if c.get("answer_state") == "blank":
                continue
            v = str(c.get("verdict") or "").strip().lower()
            if v == "incorrect":
                wrong_count += 1
            elif v == "uncertain":
                uncertain_count += 1
        page_summaries.append(
            {
                "page_index": int(page_index),
                "wrong_count": int(wrong_count),
                "uncertain_count": int(uncertain_count),
                "blank_count": int(blank_count),
                "needs_review": bool(uncertain_count > 0),
            }
        )

    # If total_pages is unknown but questions have page_index, infer it.
    if total_pages <= 0 and max_page_index >= 0:
        total_pages = int(max_page_index) + 1

    detail = SubmissionDetailResponse(
        submission_id=str(row.get("submission_id") or sid),
        profile_id=(str(row.get("profile_id") or "").strip() or None),
        created_at=str(row.get("created_at") or ""),
        subject=(str(row.get("subject") or "").strip() or None),
        total_pages=int(total_pages),
        done_pages=int(total_pages) if questions else 0,
        session_id=(str(row.get("session_id") or "").strip() or None),
        page_image_urls=page_image_urls,
        vision_raw_text=(str(row.get("vision_raw_text") or "").strip() or None),
        question_cards=sort_question_cards(cards_by_id),
        page_summaries=page_summaries,
        questions=safe_questions,
    )
    return detail


class UpdateQuestionVerdictRequest(BaseModel):
    verdict: str = Field(..., description="New verdict: correct, incorrect, or uncertain")


@router.post("/submissions/{submission_id}/questions/{question_id}")
def update_question_verdict(
    submission_id: str,
    question_id: str,
    request: UpdateQuestionVerdictRequest,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
) -> Dict[str, Any]:
    """
    Update the verdict of a specific question within a submission.
    This allows users to manually correct AI judgments.
    """
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    profile_id = require_profile_id(user_id=user_id, x_profile_id=x_profile_id)
    default_profile_id = ensure_default_profile(user_id=str(user_id))
    sid = (submission_id or "").strip()
    qid = (question_id or "").strip()

    if not sid or not qid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing submission_id or question_id"
        )

    # Validate verdict
    valid_verdicts = {"correct", "incorrect", "uncertain"}
    verdict = str(request.verdict or "").strip().lower()
    if verdict not in valid_verdicts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid verdict. Must be one of: {valid_verdicts}"
        )

    try:
        # Fetch current submission
        q = (
            _safe_table("submissions")
            .select("submission_id,profile_id,grade_result")
            .eq("user_id", str(user_id))
            .eq("submission_id", sid)
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        resp = q.limit(1).execute()
        rows = getattr(resp, "data", None)
        row = (
            rows[0]
            if isinstance(rows, list) and rows and isinstance(rows[0], dict)
            else None
        )
        if not isinstance(row, dict):
            # Backward compatibility: legacy submissions may have NULL profile_id (pre-profiles rollout).
            # In that case, treat them as belonging to the user's default profile only.
            resp2 = (
                _safe_table("submissions")
                .select("submission_id,profile_id,grade_result")
                .eq("user_id", str(user_id))
                .eq("submission_id", sid)
                .limit(1)
                .execute()
            )
            rows2 = getattr(resp2, "data", None)
            row2 = (
                rows2[0]
                if isinstance(rows2, list) and rows2 and isinstance(rows2[0], dict)
                else None
            )
            if (
                isinstance(row2, dict)
                and row2.get("profile_id") in (None, "")
                and str(profile_id or "").strip()
                and str(profile_id).strip() == str(default_profile_id).strip()
            ):
                # Best-effort backfill: assign legacy submission to default profile.
                try:
                    _safe_table("submissions").update(
                        {
                            "profile_id": str(default_profile_id).strip(),
                            "last_active_at": datetime.now(timezone.utc).isoformat(),
                        }
                    ).eq("user_id", str(user_id)).eq("submission_id", sid).execute()
                except Exception:
                    # Keep best-effort behavior: even if backfill fails, allow verdict update to proceed.
                    pass
                row = row2
    except Exception as e:
        logger.exception("update_question_verdict failed to fetch submission")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to load submission: {e.__class__.__name__}",
        ) from e

    if not isinstance(row, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="submission not found"
        )

    # Update grade_result
    grade_result = row.get("grade_result") if isinstance(row.get("grade_result"), dict) else {}
    questions = grade_result.get("questions") if isinstance(grade_result.get("questions"), list) else []

    # Find and update the question
    from homework_agent.core.question_cards import infer_answer_state

    question_found = False
    effective_verdict = verdict
    qid_qn: Optional[str] = None
    try:
        import re

        m = re.search(r":q:([^/]+)$", qid)
        if m and m.group(1):
            qid_qn = _normalize_question_key(m.group(1))
        elif qid.startswith("q:"):
            qid_qn = _normalize_question_key(qid[2:])
    except Exception:
        qid_qn = None

    for q in questions:
        if not isinstance(q, dict):
            continue
        if str(q.get("item_id") or "") != qid:
            if not qid_qn:
                continue
            if _normalize_question_key(q.get("question_number")) != qid_qn:
                continue

        ans_state = str(q.get("answer_state") or "").strip().lower()
        if not ans_state:
            ans_state = infer_answer_state(
                student_answer=q.get("student_answer"),
                answer_status=q.get("answer_status"),
            )
            q["answer_state"] = ans_state

        # Policy: blank answers are always treated as incorrect.
        if ans_state == "blank":
            q["verdict"] = "incorrect"
            q["needs_review"] = False
            effective_verdict = "incorrect"
        else:
            q["verdict"] = verdict
            q["needs_review"] = verdict == "uncertain"
        question_found = True
        break

    if not question_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="question not found in submission"
        )

    # Recalculate summary + rebuild wrong_items from questions (avoid stale aggregates).
    wrong = 0
    uncertain = 0
    blank = 0
    wrong_items: List[Dict[str, Any]] = []

    for q in questions:
        if not isinstance(q, dict):
            continue
        ans_state = str(q.get("answer_state") or "").strip().lower()
        if not ans_state:
            ans_state = infer_answer_state(
                student_answer=q.get("student_answer"),
                answer_status=q.get("answer_status"),
            )
            q["answer_state"] = ans_state

        if ans_state == "blank":
            blank += 1
            continue

        v = str(q.get("verdict") or "").strip().lower()
        if v == "incorrect":
            wrong += 1
        elif v == "uncertain":
            uncertain += 1

        if v in {"incorrect", "uncertain"}:
            item: Dict[str, Any] = {
                "item_id": str(q.get("item_id") or "").strip() or None,
                "question_number": q.get("question_number"),
                "reason": q.get("reason")
                or ("用户标记为待定" if v == "uncertain" else "用户标记为错题"),
                "knowledge_tags": q.get("knowledge_tags") or [],
                "severity": q.get("severity"),
            }
            wrong_items.append({k: val for k, val in item.items() if val is not None})

    grade_result["wrong_count"] = int(wrong)
    grade_result["uncertain_count"] = int(uncertain)
    grade_result["blank_count"] = int(blank)
    grade_result["total_items"] = int(len([q for q in questions if isinstance(q, dict)]))
    grade_result["wrong_items"] = wrong_items

    # Update submission in database
    try:
        q = _safe_table("submissions").update(
            {
                "grade_result": grade_result,
                "last_active_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        q = q.eq("user_id", str(user_id)).eq("submission_id", sid)
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        q.execute()
    except Exception as e:
        logger.exception("update_question_verdict failed to update submission")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to update submission: {e.__class__.__name__}",
        )

    return {
        "success": True,
        "submission_id": sid,
        "question_id": qid,
        "verdict": effective_verdict,
        "summary": {
            "total_items": grade_result.get("total_items"),
            "wrong_count": grade_result.get("wrong_count"),
            "uncertain_count": grade_result.get("uncertain_count"),
            "blank_count": grade_result.get("blank_count"),
        },
    }


class RebuildQIndexRequest(BaseModel):
    question_numbers: Optional[List[str]] = Field(
        default=None, description="Optional allowlist of question numbers"
    )


@router.post("/submissions/{submission_id}/qindex/rebuild")
def rebuild_submission_qindex(
    submission_id: str,
    request: RebuildQIndexRequest,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
) -> Dict[str, Any]:
    """
    Best-effort: enqueue a qindex rebuild job for an existing submission.
    This helps backfill figure slices for older submissions.
    """
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    profile_id = require_profile_id(user_id=user_id, x_profile_id=x_profile_id)
    sid = (submission_id or "").strip()
    if not sid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="missing submission_id"
        )

    try:
        q = _safe_table("submissions").select(
            "submission_id,session_id,page_image_urls,proxy_page_image_urls"
        )
        q = q.eq("user_id", str(user_id)).eq("submission_id", sid)
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        resp = q.limit(1).execute()
        rows = getattr(resp, "data", None)
        row = (
            rows[0]
            if isinstance(rows, list) and rows and isinstance(rows[0], dict)
            else None
        )
    except Exception as e:
        logger.exception("rebuild_submission_qindex failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to load submission: {e.__class__.__name__}",
        )

    if not isinstance(row, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="submission not found"
        )

    session_id = str(row.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="submission has no session_id; cannot rebuild qindex",
        )

    proxy_urls = row.get("proxy_page_image_urls")
    proxy_urls = (
        [str(u).strip() for u in proxy_urls if str(u).strip()]
        if isinstance(proxy_urls, list)
        else []
    )
    page_urls = row.get("page_image_urls")
    page_urls = (
        [str(u).strip() for u in page_urls if str(u).strip()]
        if isinstance(page_urls, list)
        else []
    )
    urls = proxy_urls or page_urls
    if not urls:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="submission has no page_image_urls; cannot rebuild qindex",
        )

    allow = (
        [str(x).strip() for x in (request.question_numbers or []) if str(x).strip()]
        if request and request.question_numbers
        else None
    )
    ok = enqueue_qindex_job(session_id=session_id, page_urls=urls, question_numbers=allow)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="qindex queue unavailable (REDIS_URL not configured?)",
        )
    return {
        "success": True,
        "submission_id": sid,
        "session_id": session_id,
        "pages": len(urls),
        "questions": len(allow or []),
    }


class MoveProfileRequest(BaseModel):
    to_profile_id: str = Field(min_length=1, description="Destination profile_id")


@router.post("/submissions/{submission_id}/move_profile")
def move_submission_profile(
    submission_id: str,
    request: MoveProfileRequest,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
) -> Dict[str, Any]:
    """
    Move a submission and its derived facts to another profile_id (same user only).
    v1 scope:
    - submissions
    - qindex_slices
    - question_attempts
    - question_steps
    - mistake_exclusions (merged with upsert to avoid unique conflicts)
    """
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    from_profile_id = require_profile_id(user_id=user_id, x_profile_id=x_profile_id)
    to_profile_id = str(getattr(request, "to_profile_id", "") or "").strip()
    sid = str(submission_id or "").strip()

    if not sid:
        raise HTTPException(status_code=400, detail="missing submission_id")
    if not to_profile_id:
        raise HTTPException(status_code=400, detail="to_profile_id is required")
    if from_profile_id and to_profile_id == from_profile_id:
        return {"ok": True}

    validate_profile_ownership(user_id=user_id, profile_id=to_profile_id)

    # Ensure the submission exists under the caller (best-effort also respects from_profile_id when present).
    try:
        q = (
            _safe_table("submissions")
            .select("submission_id,profile_id")
            .eq("user_id", str(user_id))
            .eq("submission_id", sid)
        )
        if from_profile_id:
            q = q.eq("profile_id", str(from_profile_id))
        resp = q.limit(1).execute()
        rows = getattr(resp, "data", None)
        row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
    except Exception as e:
        logger.exception("move_profile failed to load submission")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to load submission: {e.__class__.__name__}",
        ) from e

    if not isinstance(row, dict):
        raise HTTPException(status_code=404, detail="submission not found")

    now = datetime.now(timezone.utc).isoformat()

    def _update_table_profile(table: str) -> None:
        q2 = (
            _safe_table(table)
            .update({"profile_id": to_profile_id})
            .eq("user_id", str(user_id))
            .eq("submission_id", sid)
        )
        if from_profile_id:
            q2 = q2.eq("profile_id", str(from_profile_id))
        q2.execute()

    try:
        # Move main submission
        q3 = (
            _safe_table("submissions")
            .update({"profile_id": to_profile_id, "last_active_at": now})
            .eq("user_id", str(user_id))
            .eq("submission_id", sid)
        )
        if from_profile_id:
            q3 = q3.eq("profile_id", str(from_profile_id))
        q3.execute()

        # Move derived tables
        _update_table_profile("qindex_slices")
        _update_table_profile("question_attempts")
        _update_table_profile("question_steps")

        # Merge exclusions to avoid unique conflicts.
        ex_q = (
            _safe_table("mistake_exclusions")
            .select("submission_id,item_id,reason,excluded_at")
            .eq("user_id", str(user_id))
            .eq("submission_id", sid)
        )
        if from_profile_id:
            ex_q = ex_q.eq("profile_id", str(from_profile_id))
        ex_rows = getattr(ex_q.limit(5000).execute(), "data", None)
        for r in ex_rows if isinstance(ex_rows, list) else []:
            if not isinstance(r, dict):
                continue
            item_id = str(r.get("item_id") or "").strip()
            if not item_id:
                continue
            payload = {
                "user_id": str(user_id),
                "profile_id": to_profile_id,
                "submission_id": sid,
                "item_id": item_id,
                "reason": (str(r.get("reason") or "").strip() or None),
                "excluded_at": (str(r.get("excluded_at") or "").strip() or None),
            }
            _safe_table("mistake_exclusions").upsert(
                payload, on_conflict="user_id,profile_id,submission_id,item_id"
            ).execute()
        del_q = (
            _safe_table("mistake_exclusions")
            .delete()
            .eq("user_id", str(user_id))
            .eq("submission_id", sid)
        )
        if from_profile_id:
            del_q = del_q.eq("profile_id", str(from_profile_id))
        del_q.execute()

        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("move_profile failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"failed to move submission profile: {e.__class__.__name__}",
        ) from e
