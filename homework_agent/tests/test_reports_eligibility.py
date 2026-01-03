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

    def gte(self, key: str, value: Any):
        self._filters.append(("gte", str(key), value))
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
            elif op == "gte":
                if k == "created_at":
                    bound = _parse_dt(str(v))
                    if bound is not None:
                        rows = [
                            r
                            for r in rows
                            if _dt_or_min(str(r.get(k) or "")) >= bound
                        ]
                else:
                    rows = [r for r in rows if str(r.get(k) or "") >= str(v)]

        if self._order is not None:
            k, desc = self._order
            if k == "created_at":
                rows.sort(
                    key=lambda r: _dt_or_min(str(r.get(k) or "")),
                    reverse=desc,
                )
            else:
                rows.sort(key=lambda r: str(r.get(k) or ""), reverse=desc)

        if self._limit is not None:
            rows = rows[: self._limit]

        return _Resp(data=rows)


def test_reports_eligibility_demo_default_counts_unique_submissions(
    monkeypatch: pytest.MonkeyPatch,
):
    fixed_now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    monkeypatch.setattr("homework_agent.api.reports._utc_now", lambda: fixed_now)

    db: Dict[str, List[Dict[str, Any]]] = {
        "submissions": [
            {
                "submission_id": "sub1",
                "user_id": "u1",
                "subject": "math",
                "created_at": "2026-01-03T10:00:00Z",
            },
            {
                "submission_id": "sub2",
                "user_id": "u1",
                "subject": "math",
                "created_at": "2026-01-03T11:00:00Z",
            },
            {
                "submission_id": "sub3",
                "user_id": "u1",
                "subject": "math",
                "created_at": "2026-01-02T10:00:00Z",
            },
        ]
    }

    monkeypatch.setattr(
        "homework_agent.api.reports._safe_table",
        lambda name: _FakeTable(name, db),
    )

    resp = client.get("/api/v1/reports/eligibility", headers={"X-User-Id": "u1"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["eligible"] is True
    assert payload["submission_count"] == 3
    assert payload["required_count"] == 3
    assert payload["distinct_days"] == 2
    assert payload["required_days"] == 0
    assert payload["reason"] is None
    assert payload["progress_percent"] == 100


def test_reports_eligibility_periodic_requires_distinct_days(
    monkeypatch: pytest.MonkeyPatch,
):
    fixed_now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    monkeypatch.setattr("homework_agent.api.reports._utc_now", lambda: fixed_now)

    db: Dict[str, List[Dict[str, Any]]] = {
        "submissions": [
            {
                "submission_id": "sub1",
                "user_id": "u1",
                "subject": "math",
                "created_at": "2026-01-03T10:00:00Z",
            },
            {
                "submission_id": "sub2",
                "user_id": "u1",
                "subject": "math",
                "created_at": "2026-01-03T11:00:00Z",
            },
            {
                "submission_id": "sub3",
                "user_id": "u1",
                "subject": "math",
                "created_at": "2026-01-02T10:00:00Z",
            },
        ]
    }

    monkeypatch.setattr(
        "homework_agent.api.reports._safe_table",
        lambda name: _FakeTable(name, db),
    )

    resp = client.get(
        "/api/v1/reports/eligibility?mode=periodic&subject=math",
        headers={"X-User-Id": "u1"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["eligible"] is False
    assert payload["submission_count"] == 3
    assert payload["distinct_days"] == 2
    assert payload["required_days"] == 3
    assert payload["reason"] == "need_more_days"
    assert payload["subject"] == "math"


def test_reports_eligibility_subject_filter_and_window_days(
    monkeypatch: pytest.MonkeyPatch,
):
    fixed_now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    monkeypatch.setattr("homework_agent.api.reports._utc_now", lambda: fixed_now)

    db: Dict[str, List[Dict[str, Any]]] = {
        "submissions": [
            {
                "submission_id": "m1",
                "user_id": "u1",
                "subject": "math",
                "created_at": "2026-01-03T10:00:00Z",
            },
            {
                "submission_id": "m2",
                "user_id": "u1",
                "subject": "math",
                "created_at": "2026-01-02T10:00:00Z",
            },
            {
                "submission_id": "e1",
                "user_id": "u1",
                "subject": "english",
                "created_at": "2026-01-01T10:00:00Z",
            },
            {
                "submission_id": "old1",
                "user_id": "u1",
                "subject": "math",
                "created_at": "2025-09-01T10:00:00Z",
            },
        ]
    }

    monkeypatch.setattr(
        "homework_agent.api.reports._safe_table",
        lambda name: _FakeTable(name, db),
    )

    resp = client.get(
        "/api/v1/reports/eligibility?subject=math&window_days=30",
        headers={"X-User-Id": "u1"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["eligible"] is False
    assert payload["submission_count"] == 2  # old1 excluded by window_days, e1 excluded by subject
    assert payload["required_count"] == 3
    assert payload["reason"] == "need_more_submissions"
