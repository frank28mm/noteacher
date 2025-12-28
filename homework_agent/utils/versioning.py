from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def stable_json_hash(payload: Dict[str, Any]) -> str:
    """
    Create a stable hash for a JSON-serializable dict.
    Used for "thresholds/config snapshot" traceability in logs.
    """
    try:
        raw = json.dumps(
            payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except Exception:
        raw = repr(payload).encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def stable_text_hash(text: str) -> str:
    try:
        raw = str(text or "").encode("utf-8")
    except Exception:
        raw = b""
    return hashlib.sha256(raw).hexdigest()
