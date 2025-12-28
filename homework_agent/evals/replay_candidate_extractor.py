from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set


@dataclass(frozen=True)
class ReplayCandidate:
    request_id: str
    session_id: str
    subject: Optional[str]
    needs_review: bool
    warning_codes: List[str]
    evidence_urls: List[str]
    prompt_id: Optional[str]
    prompt_version: Optional[str]
    provider: Optional[str]
    model: Optional[str]

    def to_json(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "subject": self.subject,
            "needs_review": self.needs_review,
            "warning_codes": list(self.warning_codes),
            "evidence_urls": list(self.evidence_urls),
            "run_versions": {
                "prompt_id": self.prompt_id,
                "prompt_version": self.prompt_version,
                "provider": self.provider,
                "model": self.model,
            },
        }


def _as_str(v: Any) -> str:
    try:
        return str(v or "")
    except Exception:
        return ""


def _dedupe(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for it in items:
        s = _as_str(it).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _extract_urls(obj: Any) -> List[str]:
    urls: List[str] = []
    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith(("http://", "https://")) or s.startswith("data:image/"):
            urls.append(s)
        return urls
    if isinstance(obj, list):
        for x in obj:
            urls.extend(_extract_urls(x))
        return urls
    if isinstance(obj, dict):
        for k, v in obj.items():
            kk = _as_str(k).lower()
            if "url" in kk:
                urls.extend(_extract_urls(v))
            else:
                # Avoid scanning huge blobs; only walk one level deep.
                if isinstance(v, dict):
                    continue
                if isinstance(v, list):
                    continue
        return urls
    return urls


def extract_replay_candidates(lines: Iterable[str]) -> List[ReplayCandidate]:
    """
    Parse JSONL logs and produce best-effort replay candidates.

    Rules:
    - Group by request_id.
    - Candidate if any event has needs_review=true, or warnings contain "needs_review",
      or warning_codes contains safety/tool failure markers.
    - Extract subject/session_id when present in any event.
    """
    by_req: Dict[str, Dict[str, Any]] = {}

    def ensure(req_id: str) -> Dict[str, Any]:
        if req_id not in by_req:
            by_req[req_id] = {
                "request_id": req_id,
                "session_id": "",
                "subject": None,
                "needs_review": False,
                "warning_codes": [],
                "evidence_urls": [],
                "prompt_id": None,
                "prompt_version": None,
                "provider": None,
                "model": None,
            }
        return by_req[req_id]

    for raw_line in lines:
        line = _as_str(raw_line).strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue

        req_id = _as_str(obj.get("request_id")).strip()
        if not req_id:
            continue
        rec = ensure(req_id)

        sess = _as_str(obj.get("session_id")).strip()
        if sess and not rec["session_id"]:
            rec["session_id"] = sess

        subj = _as_str(obj.get("subject")).strip().lower()
        if subj in {"math", "english"} and not rec["subject"]:
            rec["subject"] = subj

        if obj.get("needs_review") is True:
            rec["needs_review"] = True

        # warnings: list[str]
        ws = obj.get("warnings")
        if isinstance(ws, list) and any(
            _as_str(w).strip() == "needs_review" for w in ws
        ):
            rec["needs_review"] = True

        codes = obj.get("warning_codes")
        if isinstance(codes, list):
            rec["warning_codes"].extend(
                [_as_str(c).strip() for c in codes if _as_str(c).strip()]
            )

        # Promote common event-specific fields.
        if _as_str(obj.get("event")) == "run_versions":
            rec["prompt_id"] = _as_str(obj.get("prompt_id")).strip() or rec["prompt_id"]
            rec["prompt_version"] = (
                _as_str(obj.get("prompt_version")).strip() or rec["prompt_version"]
            )
            rec["provider"] = _as_str(obj.get("provider")).strip() or rec["provider"]
            rec["model"] = _as_str(obj.get("model")).strip() or rec["model"]

        rec["evidence_urls"].extend(_extract_urls(obj))

    out: List[ReplayCandidate] = []
    for req_id, rec in by_req.items():
        codes = _dedupe([c for c in rec.get("warning_codes") or [] if c])
        evidence_urls = _dedupe([u for u in rec.get("evidence_urls") or [] if u])
        needs_review = bool(rec.get("needs_review")) or bool(codes)
        if not needs_review:
            continue
        out.append(
            ReplayCandidate(
                request_id=req_id,
                session_id=_as_str(rec.get("session_id")).strip(),
                subject=rec.get("subject"),
                needs_review=True,
                warning_codes=codes,
                evidence_urls=evidence_urls,
                prompt_id=rec.get("prompt_id"),
                prompt_version=rec.get("prompt_version"),
                provider=rec.get("provider"),
                model=rec.get("model"),
            )
        )
    return out
