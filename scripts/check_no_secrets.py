"""
Fail CI if high-risk secrets are accidentally committed.

Focus: Supabase service role key / JWT with role=service_role.
We intentionally scan only tracked env example/template files to avoid blocking local dev `.env`.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Optional


_JWT_RE = re.compile(r"([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)")


def _b64url_decode(s: str) -> Optional[bytes]:
    try:
        pad = "=" * ((4 - (len(s) % 4)) % 4)
        return base64.urlsafe_b64decode((s + pad).encode("utf-8"))
    except Exception:
        return None


def _jwt_payload(token: str) -> Optional[dict]:
    m = _JWT_RE.search(token)
    if not m:
        return None
    payload_b = _b64url_decode(m.group(2))
    if not payload_b:
        return None
    try:
        obj = json.loads(payload_b.decode("utf-8", errors="strict"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _iter_target_files() -> Iterable[Path]:
    # Only scan repo-tracked templates/examples.
    candidates = [
        Path(".env.example"),
        Path(".env.template"),
        Path("homework_agent/.env.example"),
        Path("homework_agent/.env.template"),
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            yield p


def _check_file(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")

    # If someone adds SUPABASE_SERVICE_ROLE_KEY with a real value, fail.
    for line in text.splitlines():
        if not line.strip().startswith("SUPABASE_SERVICE_ROLE_KEY="):
            continue
        val = line.split("=", 1)[1].strip().strip('"').strip("'")
        if not val:
            continue
        # Allow explicit placeholders only.
        if val in {"<SERVICE_ROLE_KEY>", "your-service-role-key"}:
            continue
        errors.append("SUPABASE_SERVICE_ROLE_KEY appears to be set (must be empty in repo files)")

    # Catch service_role JWT accidentally pasted into SUPABASE_KEY or elsewhere.
    for m in _JWT_RE.finditer(text):
        token = m.group(0)
        payload = _jwt_payload(token)
        if not payload:
            continue
        role = str(payload.get("role") or "").strip().lower()
        if role == "service_role":
            errors.append("Found a JWT with role=service_role (must not be committed)")

    return errors


def main() -> int:
    repo = Path(".")
    if not (repo / ".git").exists():
        print("[WARN] Not a git repo; skipping secret check.")
        return 0

    failures: list[str] = []
    for p in _iter_target_files():
        errs = _check_file(p)
        for e in errs:
            failures.append(f"{p}: {e}")

    if failures:
        print("[FAIL] Potential secrets committed:")
        for f in failures:
            print(f"- {f}")
        print(
            "\nRemediation:\n"
            "- Keep service role key only in CI secret manager / worker runtime env.\n"
            "- Keep `.env.example` / `.env.template` values empty or placeholders.\n"
            "- If already leaked, rotate Supabase keys immediately.\n"
        )
        return 1

    print("[OK] No service-role secrets detected in env templates/examples.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

