from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from homework_agent.main import create_app

client = TestClient(create_app())


@dataclass
class _Resp:
    data: Any


class _FakeTable:
    def __init__(self, name: str, db: Dict[str, List[Dict[str, Any]]]):
        self._name = name
        self._db = db
        self._insert_payload: Dict[str, Any] | None = None

    def insert(self, payload: Dict[str, Any]):
        self._insert_payload = dict(payload)
        return self

    def execute(self):
        if self._insert_payload is None:
            return _Resp(data=[])
        rows = self._db.setdefault(self._name, [])
        next_id = f"job_{len(rows) + 1}"
        row = {**self._insert_payload, "id": next_id}
        if "status" not in row:
            row["status"] = "queued"
        rows.append(row)
        return _Resp(data=[row])


def test_reports_create_job_submission_mode_sets_params(
    monkeypatch: pytest.MonkeyPatch,
):
    db: Dict[str, List[Dict[str, Any]]] = {"report_jobs": []}

    monkeypatch.setattr(
        "homework_agent.api.reports._safe_table",
        lambda name: _FakeTable(name, db),
    )

    resp = client.post(
        "/api/v1/reports",
        json={"submission_id": "sub_123"},
        headers={"X-User-Id": "u1"},
    )
    assert resp.status_code == 202
    payload = resp.json()
    assert payload["job_id"].startswith("job_")

    assert len(db["report_jobs"]) == 1
    job = db["report_jobs"][0]
    assert job["user_id"] == "u1"
    params = job["params"]
    assert params["mode"] == "submission"
    assert params["submission_id"] == "sub_123"
