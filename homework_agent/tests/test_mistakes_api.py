from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from homework_agent.main import create_app


client = TestClient(create_app())


def test_mistakes_api_returns_503_when_supabase_not_configured(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)

    resp = client.get("/api/v1/mistakes", headers={"X-User-Id": "u1"})
    assert resp.status_code == 503


@dataclass
class _Resp:
    data: Any


class _FakeTable:
    def __init__(self, name: str, db: Dict[str, List[Dict[str, Any]]]):
        self._name = name
        self._db = db
        self._filters: list[tuple[str, str, Any]] = []
        self._order: Optional[tuple[str, bool]] = None
        self._limit: Optional[int] = None
        self._delete = False
        self._upsert_payload: Optional[Dict[str, Any]] = None
        self._in_filter: Optional[tuple[str, list[str]]] = None

    def select(self, _cols: str):  # noqa: ARG002
        return self

    def eq(self, key: str, value: Any):
        self._filters.append(("eq", str(key), value))
        return self

    def lt(self, key: str, value: Any):
        self._filters.append(("lt", str(key), value))
        return self

    def in_(self, key: str, values: list[str]):
        self._in_filter = (str(key), [str(v) for v in values])
        return self

    def order(self, key: str, desc: bool = False):
        self._order = (str(key), bool(desc))
        return self

    def limit(self, n: int):
        self._limit = int(n)
        return self

    def delete(self):
        self._delete = True
        return self

    def upsert(self, payload: Dict[str, Any], on_conflict: str):  # noqa: ARG002
        self._upsert_payload = dict(payload)
        return self

    def execute(self):
        rows = list(self._db.get(self._name, []))

        # Mutation mode
        if self._upsert_payload is not None:
            # Implement unique(user_id,submission_id,item_id)
            uid = str(self._upsert_payload.get("user_id") or "")
            sid = str(self._upsert_payload.get("submission_id") or "")
            iid = str(self._upsert_payload.get("item_id") or "")
            kept: List[Dict[str, Any]] = []
            replaced = False
            for r in rows:
                if (
                    str(r.get("user_id") or "") == uid
                    and str(r.get("submission_id") or "") == sid
                    and str(r.get("item_id") or "") == iid
                ):
                    kept.append(self._upsert_payload)
                    replaced = True
                else:
                    kept.append(r)
            if not replaced:
                kept.append(self._upsert_payload)
            self._db[self._name] = kept
            return _Resp(data=kept)

        if self._delete:
            def _match(r: Dict[str, Any]) -> bool:
                for op, k, v in self._filters:
                    if op == "eq" and str(r.get(k) or "") != str(v):
                        return False
                return True

            kept = [r for r in rows if not _match(r)]
            self._db[self._name] = kept
            return _Resp(data=kept)

        # Query mode
        for op, k, v in self._filters:
            if op == "eq":
                rows = [r for r in rows if str(r.get(k) or "") == str(v)]
            elif op == "lt":
                rows = [r for r in rows if str(r.get(k) or "") < str(v)]

        if self._in_filter is not None:
            k, vs = self._in_filter
            rows = [r for r in rows if str(r.get(k) or "") in set(vs)]

        if self._order is not None:
            k, desc = self._order
            rows.sort(key=lambda r: str(r.get(k) or ""), reverse=desc)

        if self._limit is not None:
            rows = rows[: self._limit]

        return _Resp(data=rows)


def test_mistakes_history_exclusions_and_stats(monkeypatch: pytest.MonkeyPatch):
    # In-memory "DB"
    db: Dict[str, List[Dict[str, Any]]] = {
        "submissions": [
            {
                "submission_id": "sub1",
                "user_id": "u1",
                "session_id": "sess1",
                "subject": "math",
                "created_at": "2025-12-29T10:00:00Z",
                "grade_result": {
                    "wrong_items": [
                        {
                            "item_id": "item-1",
                            "question_number": "1",
                            "reason": "r1",
                            "severity": "calculation",
                            "knowledge_tags": ["数学", "代数"],
                        },
                        {
                            "item_id": "item-2",
                            "question_number": "2",
                            "reason": "r2",
                            "severity": "concept",
                            "knowledge_tags": ["数学", "几何"],
                        },
                    ]
                },
            }
        ],
        "mistake_exclusions": [{"user_id": "u1", "submission_id": "sub1", "item_id": "item-2"}],
    }

    monkeypatch.setattr(
        "homework_agent.services.mistakes_service._safe_table",
        lambda name: _FakeTable(name, db),
    )

    # Default: excluded items filtered out
    resp = client.get("/api/v1/mistakes", headers={"X-User-Id": "u1"})
    assert resp.status_code == 200
    payload = resp.json()
    assert [it["item_id"] for it in payload["items"]] == ["item-1"]

    # include_excluded=true returns both
    resp2 = client.get(
        "/api/v1/mistakes?include_excluded=true", headers={"X-User-Id": "u1"}
    )
    assert resp2.status_code == 200
    payload2 = resp2.json()
    assert sorted([it["item_id"] for it in payload2["items"]]) == ["item-1", "item-2"]

    # Stats uses excluded-filtered view
    stats = client.get("/api/v1/mistakes/stats", headers={"X-User-Id": "u1"}).json()
    tags = {d["tag"]: d["count"] for d in stats["knowledge_tag_counts"]}
    assert tags.get("代数") == 1
    assert tags.get("几何") is None

    # Exclude item-1 -> empty list
    r3 = client.post(
        "/api/v1/mistakes/exclusions",
        json={"submission_id": "sub1", "item_id": "item-1", "reason": "误判"},
        headers={"X-User-Id": "u1"},
    )
    assert r3.status_code == 200
    r4 = client.get("/api/v1/mistakes", headers={"X-User-Id": "u1"}).json()
    assert r4["items"] == []

    # Restore item-2 -> only item-2 is now visible (item-1 still excluded)
    r5 = client.delete(
        "/api/v1/mistakes/exclusions/sub1/item-2", headers={"X-User-Id": "u1"}
    )
    assert r5.status_code == 200
    r6 = client.get("/api/v1/mistakes", headers={"X-User-Id": "u1"}).json()
    assert [it["item_id"] for it in r6["items"]] == ["item-2"]

