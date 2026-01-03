#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_dotenv_best_effort() -> None:
    import os
    from pathlib import Path

    # Prefer project helper (if python-dotenv exists), but fall back to a minimal parser
    # so this script works in environments without python-dotenv.
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
        raise SystemExit(
            "SUPABASE_DB_URL 未配置（需要 Postgres 直连 URL 才能执行 DDL）。"
        )
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1]
    return raw.strip()


@dataclass(frozen=True)
class SplitResult:
    statements: List[str]
    skipped_empty: int


def _split_sql(sql: str) -> SplitResult:
    """
    Split a SQL script into statements by semicolon.

    Handles:
    - single/double quoted strings
    - line comments (-- ...)
    - block comments (/* ... */)
    - dollar-quoted blocks ($$...$$ or $tag$...$tag$)
    """
    stmts: List[str] = []
    buf: List[str] = []
    i = 0
    n = len(sql)
    in_sq = False
    in_dq = False
    in_lc = False
    in_bc = False
    dollar_tag: Optional[str] = None

    def flush() -> None:
        nonlocal buf
        s = "".join(buf).strip()
        buf = []
        if s:
            stmts.append(s)

    def peek(k: int = 0) -> str:
        j = i + k
        return sql[j] if 0 <= j < n else ""

    while i < n:
        ch = sql[i]

        if in_lc:
            buf.append(ch)
            if ch == "\n":
                in_lc = False
            i += 1
            continue

        if in_bc:
            buf.append(ch)
            if ch == "*" and peek(1) == "/":
                buf.append("/")
                i += 2
                in_bc = False
                continue
            i += 1
            continue

        if dollar_tag is not None:
            buf.append(ch)
            if ch == "$":
                tag = dollar_tag
                if sql.startswith(tag, i):
                    # close tag
                    buf.append(sql[i + 1 : i + len(tag)])
                    i += len(tag)
                    dollar_tag = None
                    continue
            i += 1
            continue

        # Enter comments
        if not in_sq and not in_dq:
            if ch == "-" and peek(1) == "-":
                buf.append(ch)
                buf.append("-")
                i += 2
                in_lc = True
                continue
            if ch == "/" and peek(1) == "*":
                buf.append(ch)
                buf.append("*")
                i += 2
                in_bc = True
                continue

        # Enter dollar-quote
        if not in_sq and not in_dq and ch == "$":
            # Find $tag$ (tag can be empty -> $$)
            j = i + 1
            while j < n and sql[j] != "$" and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < n and sql[j] == "$":
                tag = sql[i : j + 1]
                dollar_tag = tag
                buf.append(tag)
                i = j + 1
                continue

        # Toggle quotes
        if ch == "'" and not in_dq:
            buf.append(ch)
            if in_sq and peek(1) == "'":
                # escaped single quote
                buf.append("'")
                i += 2
                continue
            in_sq = not in_sq
            i += 1
            continue

        if ch == '"' and not in_sq:
            buf.append(ch)
            if in_dq and peek(1) == '"':
                buf.append('"')
                i += 2
                continue
            in_dq = not in_dq
            i += 1
            continue

        if ch == ";" and not in_sq and not in_dq and dollar_tag is None:
            buf.append(ch)
            flush()
            i += 1
            continue

        buf.append(ch)
        i += 1

    # last
    flush()
    skipped = sum(1 for s in stmts if not s.strip())
    return SplitResult(statements=[s for s in stmts if s.strip()], skipped_empty=skipped)


def _iter_sql_files(paths: Iterable[str], *, dir_mode: bool = False) -> Iterator[Path]:
    for p in paths:
        path = Path(p)
        if dir_mode:
            if not path.exists() or not path.is_dir():
                raise SystemExit(f"Not a directory: {path}")
            for f in sorted(path.glob("*.sql")):
                if f.is_file():
                    yield f
        else:
            if not path.exists() or not path.is_file():
                raise SystemExit(f"Not a file: {path}")
            yield path


def _connect(db_url: str):
    try:
        import psycopg
    except Exception as e:  # pragma: no cover
        raise SystemExit(
            f"psycopg 未安装：{e}. 请先执行：python3 -m pip install -r requirements-dev.txt"
        )
    return psycopg.connect(db_url, autocommit=True)


def _apply_file(conn, *, file_path: Path, dry_run: bool) -> None:
    sql = file_path.read_text(encoding="utf-8", errors="ignore")
    parts = _split_sql(sql).statements
    if dry_run:
        print(f"[dry-run] {file_path}: {len(parts)} statements")
        return
    cur = conn.cursor()
    for idx, stmt in enumerate(parts, 1):
        try:
            cur.execute(stmt)
        except Exception as e:
            raise RuntimeError(f"{file_path} stmt#{idx} failed: {e}") from e


def main(argv: Optional[List[str]] = None) -> int:
    _load_dotenv_best_effort()

    parser = argparse.ArgumentParser(description="Apply SQL to Supabase Postgres via SUPABASE_DB_URL")
    parser.add_argument("--dry-run", action="store_true", help="Only count statements; do not execute")
    parser.add_argument(
        "--dir",
        action="store_true",
        help="Treat inputs as directories; apply all *.sql in sorted order",
    )
    parser.add_argument("paths", nargs="+", help="SQL file(s) or directory(ies)")
    args = parser.parse_args(argv)

    db_url = _get_db_url()
    conn = _connect(db_url)
    try:
        for f in _iter_sql_files(args.paths, dir_mode=bool(args.dir)):
            print(f"[apply] {f}")
            _apply_file(conn, file_path=f, dry_run=bool(args.dry_run))
        return 0
    except Exception as e:
        print(f"[apply] ERROR: {e}", file=sys.stderr)
        return 2
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
