#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--path",
        default="qa_metrics/weekly.html",
        help="Weekly report HTML file path.",
    )
    args = parser.parse_args()

    p = Path(args.path)
    if not p.exists():
        print(f"[FAIL] missing report: {p}")
        return 1
    text = p.read_text(encoding="utf-8", errors="ignore")
    if len(text.strip()) < 200:
        print(f"[FAIL] report too small: {p} ({len(text)} bytes)")
        return 1
    required = [
        "<title>Agent Weekly Report</title>",
        "<table>",
        "Agent Weekly Report",
    ]
    missing = [s for s in required if s not in text]
    if missing:
        print(f"[FAIL] report missing markers: {missing}")
        return 1
    print(f"[OK] weekly report looks valid: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

