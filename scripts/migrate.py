#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
UP_RE = re.compile(r"^(?P<num>\d{4})_[a-z0-9_]+\.up\.sql$")
DOWN_RE = re.compile(r"^(?P<num>\d{4})_[a-z0-9_]+\.down\.sql$")


def list_migrations() -> tuple[list[Path], list[Path]]:
    if not MIGRATIONS_DIR.exists():
        return [], []
    ups = sorted(p for p in MIGRATIONS_DIR.glob("*.up.sql") if p.is_file())
    downs = sorted(p for p in MIGRATIONS_DIR.glob("*.down.sql") if p.is_file())
    return ups, downs


def check_migrations() -> int:
    ups, downs = list_migrations()
    down_names = {p.name for p in downs}
    ok = True

    for p in ups:
        if not UP_RE.match(p.name):
            print(f"[migrate] invalid up filename: {p.name}", file=sys.stderr)
            ok = False
            continue
        down = p.name.replace(".up.sql", ".down.sql")
        if down not in down_names:
            print(f"[migrate] missing down migration for: {p.name}", file=sys.stderr)
            ok = False

    for p in downs:
        if not DOWN_RE.match(p.name):
            print(f"[migrate] invalid down filename: {p.name}", file=sys.stderr)
            ok = False

    if not ups:
        print("[migrate] no migrations found (migrations/*.up.sql)")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("check")
    args = parser.parse_args()

    if args.cmd == "list":
        ups, _ = list_migrations()
        for p in ups:
            print(p.name)
        return 0
    if args.cmd == "check":
        return check_migrations()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
