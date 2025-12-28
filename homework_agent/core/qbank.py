"""
Question bank utilities.

This module is kept as a stable import surface for the rest of the codebase.
Implementation is split into:
- `qbank_parser.py`: Vision raw text → baseline question bank
- `qbank_builder.py`: merge grader outputs, sanitize/dedupe wrong items
"""

from __future__ import annotations

from homework_agent.core.qbank_parser import (
    _normalize_question_number,
    build_question_bank_from_vision_raw_text,
)
from homework_agent.core.qbank_builder import (
    sanitize_wrong_items,
    normalize_questions,
    build_question_bank,
    derive_wrong_items_from_questions,
    assign_stable_item_ids,
    dedupe_wrong_items,
)

__all__ = [
    "_normalize_question_number",
    "build_question_bank_from_vision_raw_text",
    "sanitize_wrong_items",
    "normalize_questions",
    "build_question_bank",
    "derive_wrong_items_from_questions",
    "assign_stable_item_ids",
    "dedupe_wrong_items",
]
