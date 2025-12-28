#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from homework_agent.evals.replay_candidate_extractor import extract_replay_candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract replay candidates from JSONL logs (needs_review).")
    parser.add_argument("--log", required=True, help="Path to JSONL log file (one JSON object per line).")
    parser.add_argument(
        "--out",
        default="qa_replay_candidates",
        help="Output directory (will be created).",
    )
    args = parser.parse_args()

    log_path = Path(args.log)
    if not log_path.exists():
        print(f"[FAIL] log not found: {log_path}")
        return 2
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    candidates = extract_replay_candidates(lines)
    if not candidates:
        print("[OK] no needs_review candidates found")
        return 0

    for c in candidates:
        safe_id = c.request_id.replace("/", "_")
        p = out_dir / f"{safe_id}.json"
        p.write_text(json.dumps(c.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] wrote {len(candidates)} candidate(s) to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
