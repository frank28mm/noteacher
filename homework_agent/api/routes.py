"""
API router aggregation + backward-compatible re-exports.

Why:
- Keep `homework_agent/main.py` stable: it imports `homework_agent.api.routes.router`.
- Keep scripts/tests/workers stable: they import helpers from `homework_agent.api.routes`.
"""

from __future__ import annotations

from fastapi import APIRouter

from homework_agent.api import chat as chat_api
from homework_agent.api import grade as grade_api
from homework_agent.api import session as session_api
from homework_agent.api import upload as upload_api
from homework_agent.api import review as review_api
from homework_agent.api import reviewer_ui as reviewer_ui_api
from homework_agent.api import mistakes as mistakes_api
from homework_agent.api import reports as reports_api

router = APIRouter()
router.include_router(grade_api.router)
router.include_router(chat_api.router)
router.include_router(session_api.router)
router.include_router(upload_api.router)
router.include_router(review_api.router)
router.include_router(reviewer_ui_api.router)
router.include_router(mistakes_api.router)
router.include_router(reports_api.router)

# Backward-compatible re-exports (tests/scripts/worker rely on these names)
cache_store = session_api.cache_store

save_mistakes = session_api.save_mistakes
get_mistakes = session_api.get_mistakes

_build_question_index_for_pages = session_api._build_question_index_for_pages

normalize_context_ids = chat_api.normalize_context_ids
resolve_context_items = chat_api.resolve_context_items
assistant_tail = chat_api.assistant_tail
