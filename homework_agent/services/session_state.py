from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod

from homework_agent.utils.cache import get_cache_store

try:
    from homework_agent.api.session import SESSION_TTL_SECONDS
except Exception:
    SESSION_TTL_SECONDS = None


@dataclass
class SessionState:
    session_id: str
    image_urls: List[str]
    slice_urls: Dict[str, List[str]] = field(
        default_factory=lambda: {"figure": [], "question": []}
    )
    ocr_text: Optional[str] = None
    plan_history: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: Dict[str, Any] = field(default_factory=dict)
    reflection_count: int = 0
    partial_results: Dict[str, Any] = field(default_factory=dict)
    slice_failed_cache: Dict[str, bool] = field(default_factory=dict)
    attempted_tools: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    preprocess_meta: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "image_urls": list(self.image_urls or []),
            "slice_urls": dict(self.slice_urls or {"figure": [], "question": []}),
            "ocr_text": self.ocr_text,
            "plan_history": list(self.plan_history or []),
            "tool_results": dict(self.tool_results or {}),
            "reflection_count": int(self.reflection_count or 0),
            "partial_results": dict(self.partial_results or {}),
            "slice_failed_cache": dict(self.slice_failed_cache or {}),
            "attempted_tools": dict(self.attempted_tools or {}),
            "preprocess_meta": dict(self.preprocess_meta or {}),
            "warnings": list(self.warnings or []),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        payload = data or {}
        return cls(
            session_id=str(payload.get("session_id") or ""),
            image_urls=list(payload.get("image_urls") or []),
            slice_urls=dict(
                payload.get("slice_urls") or {"figure": [], "question": []}
            ),
            ocr_text=payload.get("ocr_text"),
            plan_history=list(payload.get("plan_history") or []),
            tool_results=dict(payload.get("tool_results") or {}),
            reflection_count=int(payload.get("reflection_count") or 0),
            partial_results=dict(payload.get("partial_results") or {}),
            slice_failed_cache=dict(payload.get("slice_failed_cache") or {}),
            attempted_tools=dict(payload.get("attempted_tools") or {}),
            preprocess_meta=dict(payload.get("preprocess_meta") or {}),
            warnings=list(payload.get("warnings") or []),
        )


class SessionStore(ABC):
    @abstractmethod
    def save(self, session_id: str, state: SessionState) -> None: ...

    @abstractmethod
    def load(self, session_id: str) -> Optional[SessionState]: ...


class CacheSessionStore(SessionStore):
    def __init__(self, *, ttl_seconds: Optional[int] = SESSION_TTL_SECONDS):
        self._cache = get_cache_store()
        self._ttl_seconds = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"autonomous:state:{session_id}"

    def save(self, session_id: str, state: SessionState) -> None:
        if not session_id:
            return
        self._cache.set(
            self._key(session_id),
            state.to_dict(),
            ttl_seconds=self._ttl_seconds,
        )

    def load(self, session_id: str) -> Optional[SessionState]:
        if not session_id:
            return None
        data = self._cache.get(self._key(session_id))
        if not isinstance(data, dict):
            return None
        return SessionState.from_dict(data)


_DEFAULT_SESSION_STORE: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _DEFAULT_SESSION_STORE
    if _DEFAULT_SESSION_STORE is None:
        _DEFAULT_SESSION_STORE = CacheSessionStore()
    return _DEFAULT_SESSION_STORE
