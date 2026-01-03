#!/usr/bin/env python3
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_dotenv_best_effort() -> None:
    import os
    from pathlib import Path

    try:
        from homework_agent.utils.env import load_project_dotenv

        load_project_dotenv()
    except Exception:
        pass

    if os.getenv("SUPABASE_DB_URL"):
        return

    p = Path(".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        if not k or k in os.environ:
            continue
        os.environ[k] = v.strip()


def _get_db_url() -> str:
    import os

    raw = (os.getenv("SUPABASE_DB_URL") or "").strip()
    if not raw:
        raise SystemExit("SUPABASE_DB_URL 未配置")
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1]
    return raw.strip()


def _connect(db_url: str):
    try:
        import psycopg
    except Exception as e:  # pragma: no cover
        raise SystemExit(
            f"psycopg 未安装：{e}. 请先执行：python3 -m pip install -r requirements-dev.txt"
        )
    return psycopg.connect(db_url, autocommit=True)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    details: str


def _q(cur, sql: str, params: Tuple = ()) -> List[Tuple]:
    cur.execute(sql, params)
    rows = cur.fetchall()
    return rows if isinstance(rows, list) else []


def _has_table(cur, name: str) -> bool:
    rows = _q(
        cur,
        "select 1 from information_schema.tables where table_schema='public' and table_name=%s limit 1",
        (name,),
    )
    return bool(rows)


def _has_columns(cur, *, table: str, columns: List[str]) -> Tuple[bool, List[str]]:
    rows = _q(
        cur,
        "select column_name from information_schema.columns where table_schema='public' and table_name=%s",
        (table,),
    )
    existing = {r[0] for r in rows}
    missing = [c for c in columns if c not in existing]
    return (len(missing) == 0, missing)


def _get_report_jobs_default_status(cur) -> Optional[str]:
    rows = _q(
        cur,
        """
        select column_default
        from information_schema.columns
        where table_schema='public' and table_name='report_jobs' and column_name='status'
        limit 1
        """,
    )
    if not rows:
        return None
    return str(rows[0][0] or "").strip() or None


def _rls_enabled(cur, table: str) -> Optional[bool]:
    rows = _q(
        cur,
        "select relrowsecurity from pg_class where relname=%s and relnamespace=(select oid from pg_namespace where nspname='public') limit 1",
        (table,),
    )
    if not rows:
        return None
    return bool(rows[0][0])


def _policies(cur, table: str) -> List[str]:
    rows = _q(
        cur,
        "select policyname from pg_policies where schemaname='public' and tablename=%s",
        (table,),
    )
    return [str(r[0]) for r in rows if r and r[0]]


def main() -> int:
    _load_dotenv_best_effort()
    conn = _connect(_get_db_url())
    checks: List[Check] = []
    try:
        cur = conn.cursor()

        # report_jobs
        checks.append(
            Check(
                name="table:report_jobs",
                ok=_has_table(cur, "report_jobs"),
                details="must exist for report worker locking/state",
            )
        )
        if _has_table(cur, "report_jobs"):
            ok_cols, missing = _has_columns(
                cur,
                table="report_jobs",
                columns=[
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
            )
            checks.append(
                Check(
                    name="cols:report_jobs.lock_fields",
                    ok=ok_cols,
                    details="missing: " + (",".join(missing) if missing else "none"),
                )
            )
            default_status = _get_report_jobs_default_status(cur) or ""
            checks.append(
                Check(
                    name="default:report_jobs.status",
                    ok=("queued" in default_status),
                    details=f"column_default={default_status or 'NULL'} (expect contains 'queued')",
                )
            )
            rls = _rls_enabled(cur, "report_jobs")
            checks.append(
                Check(
                    name="rls:report_jobs",
                    ok=bool(rls),
                    details=f"relrowsecurity={rls}",
                )
            )
            pol = _policies(cur, "report_jobs")
            checks.append(
                Check(
                    name="policies:report_jobs",
                    ok=len(pol) > 0,
                    details=",".join(sorted(pol)) if pol else "(none)",
                )
            )

        # facts tables
        for t in ("question_attempts", "question_steps"):
            checks.append(Check(name=f"table:{t}", ok=_has_table(cur, t), details="facts worker output"))
            if _has_table(cur, t):
                rls = _rls_enabled(cur, t)
                checks.append(Check(name=f"rls:{t}", ok=bool(rls), details=f"relrowsecurity={rls}"))

        # submissions expected columns for facts/rehydrate
        if _has_table(cur, "submissions"):
            ok_cols, missing = _has_columns(
                cur,
                table="submissions",
                columns=[
                    "submission_id",
                    "user_id",
                    "created_at",
                    "subject",
                    "grade_result",
                    "vision_raw_text",
                ],
            )
            checks.append(
                Check(
                    name="cols:submissions.snapshot",
                    ok=ok_cols,
                    details="missing: " + (",".join(missing) if missing else "none"),
                )
            )
        else:
            checks.append(Check(name="table:submissions", ok=False, details="missing submissions table"))

        # print summary
        ok_all = True
        for c in checks:
            ok_all = ok_all and c.ok
            status = "OK " if c.ok else "FAIL"
            print(f"[{status}] {c.name} - {c.details}")
        return 0 if ok_all else 1
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
