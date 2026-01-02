from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional

from homework_agent.services.facts_extractor import extract_facts_from_grade_result
from homework_agent.utils.supabase_client import (
    get_service_role_storage_client,
    get_storage_client,
)
from homework_agent.utils.taxonomy import taxonomy_version


def _safe_table(name: str):
    # Prefer service role for backfills (bypass RLS); fall back to anon for dev-only setups.
    try:
        storage = get_service_role_storage_client()
    except Exception:
        storage = get_storage_client()
    return storage.client.table(name)


def _select_submissions(
    *,
    user_id: Optional[str],
    since: Optional[str],
    until: Optional[str],
    before_created_at: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    q = _safe_table("submissions").select(
        "submission_id,user_id,subject,created_at,grade_result"
    )
    if user_id:
        q = q.eq("user_id", str(user_id))
    if since:
        q = q.gte("created_at", str(since))
    if until:
        q = q.lte("created_at", str(until))
    if before_created_at:
        q = q.lt("created_at", str(before_created_at))
    q = q.order("created_at", desc=True).limit(int(limit))
    resp = q.execute()
    rows = getattr(resp, "data", None)
    return rows if isinstance(rows, list) else []


def _upsert_rows(*, table: str, rows: list[dict], on_conflict: str) -> None:
    if not rows:
        return
    _safe_table(table).upsert(rows, on_conflict=on_conflict).execute()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", default=None)
    ap.add_argument("--since", default=None, help="ISO datetime lower bound (>=)")
    ap.add_argument("--until", default=None, help="ISO datetime upper bound (<=)")
    ap.add_argument("--before-created-at", default=None, help="cursor for paging (<)")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = _select_submissions(
        user_id=args.user_id,
        since=args.since,
        until=args.until,
        before_created_at=args.before_created_at,
        limit=max(1, min(int(args.limit), 500)),
    )
    total_attempts = 0
    total_steps = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        uid = str(row.get("user_id") or "").strip()
        sid = str(row.get("submission_id") or "").strip()
        if not uid or not sid:
            continue
        facts = extract_facts_from_grade_result(
            user_id=uid,
            submission_id=sid,
            created_at=row.get("created_at"),
            subject=row.get("subject"),
            grade_result=row.get("grade_result") or {},
            taxonomy_version=taxonomy_version() or None,
        )
        total_attempts += len(facts.question_attempts)
        total_steps += len(facts.question_steps)
        if args.dry_run:
            continue
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

    print(
        f"processed_submissions={len(rows)} question_attempts={total_attempts} question_steps={total_steps} dry_run={bool(args.dry_run)}"
    )
    if rows:
        last = rows[-1] if isinstance(rows[-1], dict) else {}
        print(f"next_before_created_at={last.get('created_at')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
