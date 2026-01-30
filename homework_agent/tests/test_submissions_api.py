from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest
from fastapi.testclient import TestClient

from homework_agent.main import create_app

client = TestClient(create_app())


@dataclass
class _Resp:
    data: Any


def _parse_dt(s: str) -> Optional[datetime]:
    raw = (s or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _dt_or_min(s: str) -> datetime:
    return _parse_dt(s) or datetime.min.replace(tzinfo=timezone.utc)


class _FakeTable:
    def __init__(self, name: str, db: Dict[str, List[Dict[str, Any]]]):
        self._name = name
        self._db = db
        self._filters: List[Tuple[str, str, Any]] = []
        self._order: Optional[Tuple[str, bool]] = None
        self._limit: Optional[int] = None

    def select(self, _cols: str):  # noqa: ARG002
        return self

    def eq(self, key: str, value: Any):
        self._filters.append(("eq", str(key), value))
        return self

    def lt(self, key: str, value: Any):
        self._filters.append(("lt", str(key), value))
        return self

    def order(self, key: str, desc: bool = False):
        self._order = (str(key), bool(desc))
        return self

    def limit(self, n: int):
        self._limit = int(n)
        return self

    def execute(self):
        rows = list(self._db.get(self._name, []))

        for op, k, v in self._filters:
            if op == "eq":
                rows = [r for r in rows if str(r.get(k) or "") == str(v)]
            elif op == "lt":
                if k == "created_at":
                    bound = _parse_dt(str(v))
                    if bound is not None:
                        rows = [
                            r for r in rows if _dt_or_min(str(r.get(k) or "")) < bound
                        ]
                else:
                    rows = [r for r in rows if str(r.get(k) or "") < str(v)]

        if self._order is not None:
            k, desc = self._order
            if k == "created_at":
                rows.sort(key=lambda r: _dt_or_min(str(r.get(k) or "")), reverse=desc)
            else:
                rows.sort(key=lambda r: str(r.get(k) or ""), reverse=desc)

        if self._limit is not None:
            rows = rows[: self._limit]

        return _Resp(data=rows)


def test_list_submissions_sorted_and_includes_all_correct(
    monkeypatch: pytest.MonkeyPatch,
):
    db: Dict[str, List[Dict[str, Any]]] = {
        "submissions": [
            {
                "submission_id": "s1",
                "user_id": "u1",
                "subject": "math",
                "session_id": "sess1",
                "created_at": "2026-01-03T11:00:00Z",
                "page_image_urls": ["u1p1"],
                "grade_result": {
                    "questions": [
                        {
                            "question_number": "1",
                            "verdict": "correct",
                            "answer_state": "has_answer",
                        },
                        {
                            "question_number": "2",
                            "verdict": "correct",
                            "answer_state": "has_answer",
                        },
                    ],
                    "wrong_items": [],
                },
            },
            {
                "submission_id": "s2",
                "user_id": "u1",
                "subject": "math",
                "session_id": "sess2",
                "created_at": "2026-01-03T10:00:00Z",
                "page_image_urls": ["u1p1", "u1p2"],
                "grade_result": {
                    "questions": [
                        {
                            "question_number": "1",
                            "verdict": "incorrect",
                            "answer_state": "has_answer",
                        },
                        {
                            "question_number": "2",
                            "verdict": "uncertain",
                            "answer_state": "has_answer",
                        },
                        {
                            "question_number": "3",
                            "verdict": "correct",
                            "answer_state": "blank",
                        },
                    ],
                    "wrong_items": [{"question_number": "1", "reason": "x"}],
                },
            },
        ]
    }

    monkeypatch.setattr(
        "homework_agent.api.submissions._safe_table",
        lambda name: _FakeTable(name, db),
    )

    resp = client.get("/api/v1/submissions", headers={"X-User-Id": "u1"})
    assert resp.status_code == 200
    payload = resp.json()
    assert [i["submission_id"] for i in payload["items"]] == ["s1", "s2"]
    # all-correct submission must still appear
    assert payload["items"][0]["summary"]["wrong_count"] == 0
    assert payload["items"][0]["summary"]["total_items"] == 2
    # done_pages should be total_pages when summary exists
    assert payload["items"][0]["total_pages"] == 1
    assert payload["items"][0]["done_pages"] == 1


def test_list_submissions_subject_filter_and_before(monkeypatch: pytest.MonkeyPatch):
    db: Dict[str, List[Dict[str, Any]]] = {
        "submissions": [
            {
                "submission_id": "m1",
                "user_id": "u1",
                "subject": "math",
                "created_at": "2026-01-03T11:00:00Z",
                "page_image_urls": ["p1"],
                "grade_result": {
                    "questions": [{"question_number": "1", "verdict": "correct"}]
                },
            },
            {
                "submission_id": "e1",
                "user_id": "u1",
                "subject": "english",
                "created_at": "2026-01-03T10:00:00Z",
                "page_image_urls": ["p1"],
                "grade_result": {
                    "questions": [{"question_number": "1", "verdict": "correct"}]
                },
            },
            {
                "submission_id": "m0",
                "user_id": "u1",
                "subject": "math",
                "created_at": "2026-01-02T10:00:00Z",
                "page_image_urls": ["p1"],
                "grade_result": {
                    "questions": [{"question_number": "1", "verdict": "correct"}]
                },
            },
        ]
    }
    monkeypatch.setattr(
        "homework_agent.api.submissions._safe_table",
        lambda name: _FakeTable(name, db),
    )

    resp = client.get(
        "/api/v1/submissions?subject=math&before=2026-01-03T11:00:00Z",
        headers={"X-User-Id": "u1"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert [i["submission_id"] for i in payload["items"]] == ["m0"]


def test_list_submissions_invalid_before(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "homework_agent.api.submissions._safe_table",
        lambda name: _FakeTable(name, {"submissions": []}),
    )
    resp = client.get(
        "/api/v1/submissions?before=not-a-timestamp",
        headers={"X-User-Id": "u1"},
    )
    assert resp.status_code == 400


def test_get_submission_detail_returns_cards(monkeypatch: pytest.MonkeyPatch):
    db: Dict[str, List[Dict[str, Any]]] = {
        "submissions": [
            {
                "submission_id": "s1",
                "user_id": "u1",
                "subject": "math",
                "session_id": "sess1",
                "created_at": "2026-01-03T11:00:00Z",
                "page_image_urls": ["u1p1", "u1p2"],
                "vision_raw_text": "Q1...",
                "grade_result": {
                    "questions": [
                        {
                            "question_number": "1",
                            "page_index": 0,
                            "verdict": "incorrect",
                            "answer_state": "has_answer",
                        },
                        {
                            "question_number": "2",
                            "page_index": 1,
                            "verdict": "uncertain",
                            "answer_state": "has_answer",
                        },
                    ],
                },
            }
        ]
    }
    monkeypatch.setattr(
        "homework_agent.api.submissions._safe_table",
        lambda name: _FakeTable(name, db),
    )

    resp = client.get("/api/v1/submissions/s1", headers={"X-User-Id": "u1"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["submission_id"] == "s1"
    assert payload["total_pages"] == 2
    assert payload["done_pages"] == 2
    assert isinstance(payload["question_cards"], list) and payload["question_cards"]
    assert {c["page_index"] for c in payload["question_cards"]} == {0, 1}


def test_move_submission_profile_moves_derived_facts(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    @dataclass
    class _Resp2:
        data: Any

    class _FakeTable2:
        def __init__(self, name: str, db: Dict[str, List[Dict[str, Any]]]):
            self._name = name
            self._db = db
            self._filters: List[Tuple[str, str, Any]] = []
            self._limit: Optional[int] = None
            self._mode: str = "select"
            self._update_payload: Optional[Dict[str, Any]] = None
            self._upsert_payload: Optional[Dict[str, Any]] = None

        def select(self, _cols: str):  # noqa: ARG002
            self._mode = "select"
            return self

        def eq(self, key: str, value: Any):
            self._filters.append(("eq", str(key), value))
            return self

        def limit(self, n: int):
            self._limit = int(n)
            return self

        def update(self, payload: Dict[str, Any]):
            self._mode = "update"
            self._update_payload = dict(payload)
            return self

        def delete(self):
            self._mode = "delete"
            return self

        def upsert(self, payload: Dict[str, Any], on_conflict: str):  # noqa: ARG002
            self._mode = "upsert"
            self._upsert_payload = dict(payload)
            return self

        def execute(self):
            rows = list(self._db.get(self._name, []))

            def _match(r: Dict[str, Any]) -> bool:
                for op, k, v in self._filters:
                    if op == "eq" and str(r.get(k) or "") != str(v):
                        return False
                return True

            if self._mode == "update":
                updated: List[Dict[str, Any]] = []
                kept: List[Dict[str, Any]] = []
                for r in rows:
                    if _match(r):
                        nr = dict(r)
                        nr.update(self._update_payload or {})
                        updated.append(nr)
                        kept.append(nr)
                    else:
                        kept.append(r)
                self._db[self._name] = kept
                return _Resp2(data=updated)

            if self._mode == "delete":
                kept = [r for r in rows if not _match(r)]
                self._db[self._name] = kept
                return _Resp2(data=kept)

            if self._mode == "upsert":
                payload = dict(self._upsert_payload or {})
                uid = str(payload.get("user_id") or "")
                pid = str(payload.get("profile_id") or "")
                sid = str(payload.get("submission_id") or "")
                iid = str(payload.get("item_id") or "")
                kept2: List[Dict[str, Any]] = []
                replaced = False
                for r in rows:
                    if (
                        str(r.get("user_id") or "") == uid
                        and str(r.get("profile_id") or "") == pid
                        and str(r.get("submission_id") or "") == sid
                        and str(r.get("item_id") or "") == iid
                    ):
                        kept2.append(payload)
                        replaced = True
                    else:
                        kept2.append(r)
                if not replaced:
                    kept2.append(payload)
                self._db[self._name] = kept2
                return _Resp2(data=[payload])

            # select
            out = [r for r in rows if _match(r)]
            if self._limit is not None:
                out = out[: self._limit]
            return _Resp2(data=out)

    db: Dict[str, List[Dict[str, Any]]] = {
        "submissions": [
            {
                "submission_id": "s1",
                "user_id": "u1",
                "profile_id": "p_from",
                "created_at": "2026-01-03T11:00:00Z",
                "last_active_at": "2026-01-03T11:00:00Z",
            }
        ],
        "qindex_slices": [
            {
                "user_id": "u1",
                "profile_id": "p_from",
                "submission_id": "s1",
                "question_number": "1",
            }
        ],
        "question_attempts": [
            {
                "user_id": "u1",
                "profile_id": "p_from",
                "submission_id": "s1",
                "item_id": "i1",
            }
        ],
        "question_steps": [
            {
                "user_id": "u1",
                "profile_id": "p_from",
                "submission_id": "s1",
                "item_id": "i1",
                "step_index": 0,
            }
        ],
        "mistake_exclusions": [
            {
                "user_id": "u1",
                "profile_id": "p_from",
                "submission_id": "s1",
                "item_id": "i1",
                "reason": "x",
                "excluded_at": "2026-01-03T11:10:00Z",
            }
        ],
    }

    monkeypatch.setattr(
        "homework_agent.api.submissions._safe_table",
        lambda name: _FakeTable2(name, db),
    )

    resp = client.post(
        "/api/v1/submissions/s1/move_profile",
        json={"to_profile_id": "p_to"},
        headers={"X-User-Id": "u1", "X-Profile-Id": "p_from"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    assert db["submissions"][0]["profile_id"] == "p_to"
    assert db["qindex_slices"][0]["profile_id"] == "p_to"
    assert db["question_attempts"][0]["profile_id"] == "p_to"
    assert db["question_steps"][0]["profile_id"] == "p_to"
    # Exclusion moved (old removed, new created)
    assert len(db["mistake_exclusions"]) == 1
    assert db["mistake_exclusions"][0]["profile_id"] == "p_to"
