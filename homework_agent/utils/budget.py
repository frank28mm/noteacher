from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional


def extract_total_tokens(usage: Any) -> Optional[int]:
    """
    Best-effort extract total tokens from an OpenAI-compatible usage object/dict.
    Returns None if missing/unparseable.
    """
    if usage is None:
        return None
    if isinstance(usage, dict):
        v = usage.get("total_tokens")
    else:
        v = getattr(usage, "total_tokens", None)
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


@dataclass
class RunBudget:
    """
    Shared budget for a single request/run.

    - Time budget uses monotonic clock.
    - Token budget is best-effort and depends on providers returning usage.
    """

    deadline_m: float
    token_budget_total: Optional[int] = None
    tokens_used: int = 0

    @staticmethod
    def for_timeout_seconds(
        *, timeout_seconds: float, token_budget_total: Optional[int] = None
    ) -> "RunBudget":
        now = time.monotonic()
        return RunBudget(
            deadline_m=now + float(timeout_seconds),
            token_budget_total=token_budget_total,
        )

    def remaining_seconds(self) -> float:
        return float(self.deadline_m - time.monotonic())

    def is_time_exhausted(self) -> bool:
        return self.remaining_seconds() <= 0

    def consume_usage(self, usage: Any) -> Optional[int]:
        total = extract_total_tokens(usage)
        if total is None:
            return None
        self.tokens_used += int(total)
        return int(total)

    def is_token_exhausted(self) -> bool:
        if self.token_budget_total is None:
            return False
        return int(self.tokens_used) >= int(self.token_budget_total)
