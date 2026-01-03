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
                        rows = [r for r in rows if _dt_or_min(str(r.get(k) or "")) < bound]
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


def test_list_submissions_sorted_and_includes_all_correct(monkeypatch: pytest.MonkeyPatch):
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
                        {"question_number": "1", "verdict": "correct", "answer_state": "has_answer"},
                        {"question_number": "2", "verdict": "correct", "answer_state": "has_answer"},
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
                        {"question_number": "1", "verdict": "incorrect", "answer_state": "has_answer"},
                        {"question_number": "2", "verdict": "uncertain", "answer_state": "has_answer"},
                        {"question_number": "3", "verdict": "correct", "answer_state": "blank"},
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
                "grade_result": {"questions": [{"question_number": "1", "verdict": "correct"}]},
            },
            {
                "submission_id": "e1",
                "user_id": "u1",
                "subject": "english",
                "created_at": "2026-01-03T10:00:00Z",
                "page_image_urls": ["p1"],
                "grade_result": {"questions": [{"question_number": "1", "verdict": "correct"}]},
            },
            {
                "submission_id": "m0",
                "user_id": "u1",
                "subject": "math",
                "created_at": "2026-01-02T10:00:00Z",
                "page_image_urls": ["p1"],
                "grade_result": {"questions": [{"question_number": "1", "verdict": "correct"}]},
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
                        {"question_number": "1", "page_index": 0, "verdict": "incorrect", "answer_state": "has_answer"},
                        {"question_number": "2", "page_index": 1, "verdict": "uncertain", "answer_state": "has_answer"},
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
