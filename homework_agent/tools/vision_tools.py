from __future__ import annotations

from typing import Any, Dict

from homework_agent.core.tools import tool


@tool(
    name="correct_ocr_context",
    description="Lightly normalize OCR text (spacing/punctuation) for downstream reasoning.",
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Raw OCR text to normalize.",
            }
        },
        "required": ["text"],
    },
)
def correct_ocr_context(text: str) -> Dict[str, Any]:
    raw = str(text or "")
    cleaned = raw.replace("\r", "").replace("\t", " ")
    cleaned = " ".join(cleaned.split())
    return {
        "status": "ok",
        "normalized": cleaned,
    }

