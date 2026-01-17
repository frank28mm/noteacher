#!/usr/bin/env python3
from __future__ import annotations

"""
Verify whether migration 0012 (child_profiles + profile_id columns) has been applied,
using Supabase PostgREST (SUPABASE_URL + SUPABASE_KEY).

This avoids needing Postgres direct credentials (SUPABASE_DB_URL), and is safe to run in dev.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from homework_agent.utils.env import load_project_dotenv
from homework_agent.utils.supabase_client import get_storage_client


def _try_select(table: str, cols: str) -> Tuple[bool, str]:
    try:
        resp = get_storage_client().client.table(table).select(cols).limit(1).execute()
        _ = getattr(resp, "data", None)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def main() -> int:
    load_project_dotenv()

    checks: List[Tuple[str, str]] = [
        ("child_profiles", "profile_id,user_id,display_name,is_default,created_at"),
        ("submissions", "submission_id,user_id,profile_id,created_at"),
        ("qindex_slices", "user_id,profile_id,submission_id,question_number"),
        ("question_attempts", "user_id,profile_id,submission_id,item_id"),
        ("question_steps", "user_id,profile_id,submission_id,item_id,step_index"),
        ("mistake_exclusions", "user_id,profile_id,submission_id,item_id"),
        ("report_jobs", "id,user_id,profile_id,status,created_at"),
        ("reports", "id,user_id,profile_id,created_at"),
    ]

    ok_all = True
    for table, cols in checks:
        ok, msg = _try_select(table, cols)
        ok_all = ok_all and ok
        print(f"[{'OK ' if ok else 'FAIL'}] {table} select({cols}) - {msg}")

    if not ok_all:
        print(
            "\n=> 结论：0012 未在当前配置的 Supabase 数据库生效（child_profiles 或 profile_id 列缺失）。\n"
            "请在 Supabase SQL Editor 执行：migrations/0012_add_child_profiles_and_profile_id.up.sql\n",
            file=sys.stderr,
        )
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())

