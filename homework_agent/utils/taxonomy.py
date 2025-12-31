from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _taxonomy_path() -> Path:
    # homework_agent/utils/taxonomy.py -> homework_agent/resources/knowledge_taxonomy_v0.json
    return (
        Path(__file__).resolve().parents[1]
        / "resources"
        / "knowledge_taxonomy_v0.json"
    )


@lru_cache(maxsize=1)
def load_taxonomy_v0() -> Dict[str, Any]:
    path = _taxonomy_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def taxonomy_version() -> str:
    data = load_taxonomy_v0()
    v = data.get("version")
    return str(v).strip() if v is not None else ""


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for s in items:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def normalize_knowledge_tags(tags: List[str]) -> List[str]:
    """
    Normalize knowledge tags with repo-tracked taxonomy v0.

    Rules:
    - strip + drop empty
    - apply deprecated mapping first, then alias mapping
    - dedupe while preserving order
    """
    data = load_taxonomy_v0()
    aliases = data.get("aliases") if isinstance(data.get("aliases"), dict) else {}
    deprecated = (
        data.get("deprecated") if isinstance(data.get("deprecated"), dict) else {}
    )
    unknown_policy = str(data.get("unknown_policy") or "keep").strip().lower()

    normalized: List[str] = []
    for t in tags or []:
        s = str(t or "").strip()
        if not s:
            continue
        s = str(deprecated.get(s) or s).strip()
        s = str(aliases.get(s) or s).strip()
        if not s:
            continue
        if unknown_policy == "drop" and s not in aliases.values() and s not in deprecated.values():
            continue
        normalized.append(s)
    return _dedupe_keep_order(normalized)

