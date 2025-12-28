from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _now_ms() -> int:
    return int(time.time() * 1000)


def _trim_large(value: Any, *, max_len: int = 2000) -> Any:
    """
    Prevent accidentally persisting huge blobs (e.g., base64 images) in tool outputs.
    Best-effort; never raises.
    """
    try:
        if value is None:
            return None
        if isinstance(value, str):
            s = value
            if s.startswith("data:image/"):
                return "data:image/...;base64,<omitted>"
            if len(s) > max_len:
                return s[:max_len] + "…"
            return s
        if isinstance(value, (int, float, bool)):
            return value
        if isinstance(value, list):
            return [_trim_large(v, max_len=max_len) for v in value]
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for k, v in value.items():
                out[str(k)] = _trim_large(v, max_len=max_len)
            return out
        return _trim_large(str(value), max_len=max_len)
    except Exception:
        try:
            return str(value)[:max_len] + "…"
        except Exception:
            return "<unserializable>"


@dataclass(frozen=True)
class ToolResult:
    """
    Unified tool result contract (success or failure).

    This is intentionally minimal and JSON-friendly. Callers can still merge legacy keys
    into the output dict for backward compatibility.
    """

    ok: bool
    tool_name: str
    stage: str
    request_id: str
    session_id: str
    timing_ms: int

    data: Any = None
    warnings: List[str] = field(default_factory=list)
    needs_review: bool = False

    error_type: Optional[str] = None
    error_code: Optional[str] = None
    retryable: bool = False
    fallback_used: Optional[str] = None

    warning_codes: List[str] = field(default_factory=list)

    # For backward compatibility / debugging (sanitized + truncated).
    raw: Dict[str, Any] = field(default_factory=dict)

    created_at_ms: int = field(default_factory=_now_ms)

    @staticmethod
    def success(
        *,
        tool_name: str,
        stage: str,
        request_id: str,
        session_id: str,
        timing_ms: int,
        data: Any = None,
        warnings: Optional[List[str]] = None,
        needs_review: bool = False,
        warning_codes: Optional[List[str]] = None,
        raw: Optional[Dict[str, Any]] = None,
        fallback_used: Optional[str] = None,
    ) -> "ToolResult":
        return ToolResult(
            ok=True,
            tool_name=str(tool_name or ""),
            stage=str(stage or ""),
            request_id=str(request_id or ""),
            session_id=str(session_id or ""),
            timing_ms=int(timing_ms),
            data=data,
            warnings=list(warnings or []),
            needs_review=bool(needs_review),
            warning_codes=list(warning_codes or []),
            raw=dict(raw or {}),
            fallback_used=fallback_used,
        )

    @staticmethod
    def error(
        *,
        tool_name: str,
        stage: str,
        request_id: str,
        session_id: str,
        timing_ms: int,
        error_type: str,
        error_code: Optional[str] = None,
        retryable: bool = False,
        fallback_used: Optional[str] = None,
        warnings: Optional[List[str]] = None,
        needs_review: bool = True,
        warning_codes: Optional[List[str]] = None,
        raw: Optional[Dict[str, Any]] = None,
        data: Any = None,
    ) -> "ToolResult":
        return ToolResult(
            ok=False,
            tool_name=str(tool_name or ""),
            stage=str(stage or ""),
            request_id=str(request_id or ""),
            session_id=str(session_id or ""),
            timing_ms=int(timing_ms),
            data=data,
            warnings=list(warnings or []),
            needs_review=bool(needs_review),
            error_type=str(error_type or "ToolError"),
            error_code=str(error_code) if error_code else None,
            retryable=bool(retryable),
            fallback_used=fallback_used,
            warning_codes=list(warning_codes or []),
            raw=dict(raw or {}),
        )

    @staticmethod
    def from_legacy(
        *,
        tool_name: str,
        stage: str,
        raw: Any,
        request_id: Optional[str],
        session_id: Optional[str],
        timing_ms: int,
    ) -> "ToolResult":
        """
        Convert legacy dict tool outputs into unified ToolResult.
        This never raises.
        """
        tool = str(tool_name or "").strip() or "unknown_tool"
        stage_s = str(stage or "").strip() or "unknown_stage"
        rid = str(request_id or "").strip()
        sid = str(session_id or "").strip()

        try:
            d: Dict[str, Any] = (
                raw
                if isinstance(raw, dict)
                else {"status": "error", "message": "tool_result_not_dict"}
            )

            status = str(d.get("status") or "").strip().lower()
            ok = (
                bool(d.get("ok"))
                if "ok" in d
                else status in {"ok", "degraded", "empty"}
            )

            warnings: List[str] = []
            w_list = d.get("warnings")
            if isinstance(w_list, list):
                warnings.extend([str(x) for x in w_list if str(x or "").strip()])
            w_single = d.get("warning")
            if isinstance(w_single, str) and w_single.strip():
                warnings.append(w_single.strip())

            warning_codes: List[str] = []
            wc = d.get("warning_codes")
            if isinstance(wc, list):
                warning_codes.extend([str(x) for x in wc if str(x or "").strip()])

            needs_review = bool(d.get("needs_review")) if "needs_review" in d else False
            retryable = bool(d.get("retryable")) if "retryable" in d else False
            error_type = d.get("error_type")
            error_code = d.get("error_code")
            fallback_used = d.get("fallback_used")
            if not fallback_used:
                if status == "degraded":
                    fallback_used = "degraded"
                elif "ocr_fallback" in d:
                    fallback_used = "ocr_fallback"
                elif d.get("cached") is True:
                    fallback_used = "cache"

            # Safety scan can promote needs_review and warning_codes.
            try:
                from homework_agent.security.safety import (
                    scan_safety,
                    sanitize_value_for_log,
                )

                scan = scan_safety(d)
                if scan.warning_codes:
                    warning_codes.extend(scan.warning_codes)
                    needs_review = needs_review or bool(scan.needs_review)
                safe_raw = sanitize_value_for_log(_trim_large(d))
            except Exception:
                safe_raw = _trim_large(d)

            # If error-ish, force needs_review unless explicitly suppressed.
            if not ok and status in {"", "error"}:
                needs_review = True
                if not error_type:
                    error_type = "ToolError"
                if not error_code:
                    error_code = "tool_failed"
                if not warning_codes:
                    warning_codes = [f"tool_error:{tool}"]

            # De-dupe warning codes (preserve order).
            seen = set()
            deduped_codes: List[str] = []
            for c in warning_codes:
                cs = str(c or "").strip()
                if not cs or cs in seen:
                    continue
                seen.add(cs)
                deduped_codes.append(cs)

            # Keep original payload under data (sanitized).
            data = safe_raw

            if ok:
                return ToolResult.success(
                    tool_name=tool,
                    stage=stage_s,
                    request_id=rid,
                    session_id=sid,
                    timing_ms=int(timing_ms),
                    data=data,
                    warnings=warnings,
                    needs_review=needs_review,
                    warning_codes=deduped_codes,
                    raw=safe_raw if isinstance(safe_raw, dict) else {"value": safe_raw},
                    fallback_used=str(fallback_used) if fallback_used else None,
                )
            return ToolResult.error(
                tool_name=tool,
                stage=stage_s,
                request_id=rid,
                session_id=sid,
                timing_ms=int(timing_ms),
                data=data,
                warnings=warnings,
                needs_review=True if needs_review else True,
                error_type=str(error_type or "ToolError"),
                error_code=str(error_code) if error_code else None,
                retryable=bool(retryable),
                fallback_used=str(fallback_used) if fallback_used else None,
                warning_codes=deduped_codes,
                raw=safe_raw if isinstance(safe_raw, dict) else {"value": safe_raw},
            )
        except Exception as e:
            return ToolResult.error(
                tool_name=tool,
                stage=stage_s,
                request_id=rid,
                session_id=sid,
                timing_ms=int(timing_ms),
                error_type="ToolResultParseError",
                error_code="tool_result_parse_error",
                retryable=False,
                warnings=["tool_result_parse_error"],
                warning_codes=["tool_result_parse_error"],
                raw={"error": str(e)},
            )

    def to_dict(self, *, merge_raw: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if merge_raw and isinstance(self.raw, dict):
            payload.update(self.raw)
        payload.update(
            {
                "ok": bool(self.ok),
                "tool_name": self.tool_name,
                "stage": self.stage,
                "request_id": self.request_id,
                "session_id": self.session_id,
                "timing_ms": int(self.timing_ms),
                "data": self.data,
                "warnings": list(self.warnings or []),
                "needs_review": bool(self.needs_review),
                "warning_codes": list(self.warning_codes or []),
                "error_type": self.error_type,
                "error_code": self.error_code,
                "retryable": bool(self.retryable),
                "fallback_used": self.fallback_used,
                "created_at_ms": int(self.created_at_ms),
            }
        )
        return payload
