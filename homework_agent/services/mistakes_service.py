from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from homework_agent.utils.supabase_client import get_storage_client

logger = logging.getLogger(__name__)


class MistakesServiceError(RuntimeError):
    pass


def _safe_table(name: str):
    storage = get_storage_client()
    return storage.client.table(name)


def _coerce_wrong_items(grade_result: Any) -> List[Dict[str, Any]]:
    if not isinstance(grade_result, dict):
        return []
    raw = grade_result.get("wrong_items")
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out


def _stable_item_id(item: Dict[str, Any], *, fallback_idx: int) -> str:
    v = item.get("item_id") or item.get("id")
    if v is None:
        return f"item-{fallback_idx}"
    s = str(v).strip()
    return s or f"item-{fallback_idx}"


@dataclass(frozen=True)
class MistakeRow:
    submission_id: str
    session_id: Optional[str]
    subject: Optional[str]
    created_at: Optional[str]
    item_id: str
    question_number: Optional[str]
    reason: Optional[str]
    severity: Optional[str]
    knowledge_tags: List[str]
    raw: Dict[str, Any]


def list_mistakes(
    *,
    user_id: str,
    profile_id: Optional[str] = None,
    limit_submissions: int = 20,
    before_created_at: Optional[str] = None,
    include_excluded: bool = False,
) -> Tuple[List[MistakeRow], Optional[str]]:
    """
    List mistakes across submissions for a user.

    Implementation note:
    - We currently treat `submissions.grade_result.wrong_items` as the durable mistake snapshot.
    - Exclusions (if table exists) filter results by default.
    """
    if not str(user_id or "").strip():
        raise MistakesServiceError("user_id is required")
    limit = max(1, min(int(limit_submissions), 50))

    try:
        q = (
            _safe_table("submissions")
            .select("submission_id,session_id,subject,created_at,grade_result")
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
            .limit(limit)
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        if before_created_at:
            q = q.lt("created_at", str(before_created_at))
        resp = q.execute()
        rows = getattr(resp, "data", None)
        submissions = rows if isinstance(rows, list) else []
    except Exception as e:
        raise MistakesServiceError(f"failed to query submissions: {e}") from e

    submission_ids: List[str] = []
    for r in submissions:
        if isinstance(r, dict) and str(r.get("submission_id") or "").strip():
            submission_ids.append(str(r.get("submission_id")).strip())

    excluded: set[tuple[str, str]] = set()
    if submission_ids and not include_excluded:
        try:
            q = (
                _safe_table("mistake_exclusions")
                .select("submission_id,item_id")
                .eq("user_id", str(user_id))
                .in_("submission_id", submission_ids)
            )
            if profile_id:
                q = q.eq("profile_id", str(profile_id))
            ex = q.execute()
            ex_rows = getattr(ex, "data", None)
            ex_rows = ex_rows if isinstance(ex_rows, list) else []
            for r in ex_rows:
                if not isinstance(r, dict):
                    continue
                sid = str(r.get("submission_id") or "").strip()
                iid = str(r.get("item_id") or "").strip()
                if sid and iid:
                    excluded.add((sid, iid))
        except Exception:
            # Best-effort: if the exclusions table is missing/unavailable, fall back to "no exclusions".
            excluded = set()

    out: List[MistakeRow] = []
    for sidx, sub in enumerate(submissions):
        if not isinstance(sub, dict):
            continue
        submission_id = str(sub.get("submission_id") or "").strip()
        if not submission_id:
            continue
        wrong_items = _coerce_wrong_items(sub.get("grade_result"))
        for widx, item in enumerate(wrong_items):
            item_id = _stable_item_id(item, fallback_idx=widx)
            if (submission_id, item_id) in excluded:
                continue
            tags = item.get("knowledge_tags") or item.get("knowledge_tags", [])
            tags_list = (
                [str(t).strip() for t in tags if str(t).strip()]
                if isinstance(tags, list)
                else []
            )
            out.append(
                MistakeRow(
                    submission_id=submission_id,
                    session_id=(
                        str(sub.get("session_id")).strip()
                        if sub.get("session_id") is not None
                        else None
                    ),
                    subject=(
                        str(sub.get("subject")).strip()
                        if sub.get("subject") is not None
                        else None
                    ),
                    created_at=(
                        str(sub.get("created_at")).strip()
                        if sub.get("created_at") is not None
                        else None
                    ),
                    item_id=item_id,
                    question_number=(
                        str(item.get("question_number")).strip()
                        if item.get("question_number") is not None
                        else None
                    ),
                    reason=(
                        str(item.get("reason")).strip()
                        if item.get("reason") is not None
                        else None
                    ),
                    severity=(
                        str(item.get("severity")).strip()
                        if item.get("severity") is not None
                        else None
                    ),
                    knowledge_tags=tags_list,
                    raw=item,
                )
            )

    next_before = None
    if submissions:
        last = submissions[-1] if isinstance(submissions[-1], dict) else {}
        if isinstance(last, dict):
            v = str(last.get("created_at") or "").strip()
            next_before = v or None
    return out, next_before


def compute_knowledge_tag_stats(mistakes: Iterable[MistakeRow]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for m in mistakes:
        for t in m.knowledge_tags or []:
            k = str(t).strip()
            if not k:
                continue
            counts[k] = counts.get(k, 0) + 1
    items = [{"tag": k, "count": v} for k, v in counts.items()]
    items.sort(key=lambda x: (-int(x["count"]), str(x["tag"])))
    return items


def exclude_mistake(
    *,
    user_id: str,
    profile_id: Optional[str] = None,
    submission_id: str,
    item_id: str,
    reason: Optional[str] = None,
) -> None:
    if not str(user_id or "").strip():
        raise MistakesServiceError("user_id is required")
    sid = str(submission_id or "").strip()
    iid = str(item_id or "").strip()
    if not sid or not iid:
        raise MistakesServiceError("submission_id and item_id are required")
    try:
        payload: Dict[str, Any] = {
            "user_id": str(user_id),
            "profile_id": (str(profile_id).strip() if profile_id else None),
            "submission_id": sid,
            "item_id": iid,
            "reason": (str(reason).strip() if reason is not None else None),
        }
        _safe_table("mistake_exclusions").upsert(
            payload, on_conflict="user_id,profile_id,submission_id,item_id"
        ).execute()
    except Exception as e:
        raise MistakesServiceError(f"failed to upsert exclusion: {e}") from e


def restore_mistake(
    *,
    user_id: str,
    profile_id: Optional[str] = None,
    submission_id: str,
    item_id: str,
) -> None:
    if not str(user_id or "").strip():
        raise MistakesServiceError("user_id is required")
    sid = str(submission_id or "").strip()
    iid = str(item_id or "").strip()
    if not sid or not iid:
        raise MistakesServiceError("submission_id and item_id are required")
    try:
        q = (
            _safe_table("mistake_exclusions")
            .delete()
            .eq("user_id", str(user_id))
            .eq("submission_id", sid)
            .eq("item_id", iid)
        )
        if profile_id:
            q = q.eq("profile_id", str(profile_id))
        q.execute()
    except Exception as e:
        raise MistakesServiceError(f"failed to delete exclusion: {e}") from e
