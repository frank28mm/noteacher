from __future__ import annotations

from homework_agent.services.review_queue import (
    enqueue_review_item,
    list_review_items,
    resolve_review_item,
)
from homework_agent.utils.cache import InMemoryCache


def test_review_queue_enqueue_list_and_resolve_in_memory() -> None:
    cache = InMemoryCache()
    item_id = enqueue_review_item(
        request_id="req_x",
        session_id="sess_x",
        subject="math",
        warning_codes=["diagram_roi_not_found", "diagram_roi_not_found"],
        evidence_urls=[
            "https://example.com/a.png?access_token=abc",
            "data:image/png;base64,AAAA",
        ],
        run_versions={"prompt_id": "autonomous", "prompt_version": "v1"},
        cache_store=cache,
    )
    assert item_id

    items = list_review_items(status="open", limit=10, cache_store=cache)
    assert len(items) == 1
    assert items[0]["item_id"] == item_id
    assert items[0]["request_id"] == "req_x"
    assert items[0]["session_id"] == "sess_x"
    assert items[0]["status"] == "open"
    # base64 evidence should be dropped; URL token should be redacted.
    assert all(
        not str(u).startswith("data:image/")
        for u in (items[0].get("evidence_urls") or [])
    )
    assert any("access_token=" in str(u) for u in (items[0].get("evidence_urls") or []))
    assert all(
        "access_token=abc" not in str(u) for u in (items[0].get("evidence_urls") or [])
    )

    ok = resolve_review_item(
        item_id=item_id, resolved_by="tester", note="ok", cache_store=cache
    )
    assert ok is True

    open_items = list_review_items(status="open", limit=10, cache_store=cache)
    assert open_items == []
    resolved_items = list_review_items(status="resolved", limit=10, cache_store=cache)
    assert len(resolved_items) == 1
    assert resolved_items[0]["resolved_by"] == "tester"
