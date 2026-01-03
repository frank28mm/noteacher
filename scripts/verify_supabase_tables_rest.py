#!/usr/bin/env python3
from __future__ import annotations

"""
Verify key Supabase tables/columns via PostgREST (SUPABASE_URL + SUPABASE_KEY).

Why:
- Works even when Postgres direct password/DB URL is unavailable.
- Gives a quick “does the table/columns exist + selectable?” signal for P0 readiness.

Limitations:
- Cannot validate column defaults or RLS flags precisely (needs direct SQL).
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from homework_agent.utils.supabase_client import get_storage_client
from homework_agent.utils.env import load_project_dotenv


def _select_one(table: str, cols: str) -> Optional[Dict[str, Any]]:
    try:
        resp = get_storage_client().client.table(table).select(cols).limit(1).execute()
        rows = getattr(resp, "data", None)
        if isinstance(rows, list) and rows:
            return rows[0] if isinstance(rows[0], dict) else {}
        return {}
    except Exception as e:
        raise RuntimeError(f"{table}.select({cols}) failed: {e}") from e


def _check_table(table: str, cols: List[str]) -> tuple[bool, str]:
    cols_csv = ",".join(cols)
    try:
        _select_one(table, cols_csv)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def main() -> int:
    load_project_dotenv()

    checks = [
        ("submissions", ["submission_id", "user_id", "created_at", "grade_result"]),
        (
            "report_jobs",
            [
                "id",
                "user_id",
                "status",
                "params",
                "attempt_count",
                "locked_at",
                "locked_by",
                "report_id",
                "created_at",
                "updated_at",
            ],
        ),
        ("reports", ["id", "user_id", "created_at"]),
        (
            "question_attempts",
            ["user_id", "submission_id", "item_id", "verdict", "created_at"],
        ),
        (
            "question_steps",
            ["user_id", "submission_id", "item_id", "step_index", "created_at"],
        ),
    ]

    ok_all = True
    for table, cols in checks:
        ok, msg = _check_table(table, cols)
        ok_all = ok_all and ok
        print(f"[{'OK ' if ok else 'FAIL'}] {table} - {msg}")

    if not ok_all:
        print(
            "\n提示：若 report_jobs/question_attempts/question_steps 缺失，请在 Supabase SQL Editor 执行：\n"
            "- `supabase/schema.sql`\n"
            "- `supabase/patches/20260101_add_facts_tables_and_report_job_locks.sql`\n",
            file=sys.stderr,
        )
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
