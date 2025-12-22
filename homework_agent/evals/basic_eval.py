from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List

from homework_agent.services.llm import LLMClient


@dataclass
class EvalResult:
    total: int
    judged: int
    notes: List[str]


_EVAL_SYSTEM_PROMPT = (
    "你是评测裁判。请判断回答是否存在明显幻觉、是否正确调用工具。"
    "输出 JSON: {\"hallucination\": bool, \"tool_use_ok\": bool, \"notes\": string}."
)


def run_basic_eval(samples_path: str, *, provider: str = "silicon") -> EvalResult:
    client = LLMClient()
    total = 0
    judged = 0
    notes: List[str] = []
    with open(samples_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            sample = json.loads(line)
            prompt = json.dumps(sample, ensure_ascii=False)
            res = client.generate(
                prompt=prompt,
                system_prompt=_EVAL_SYSTEM_PROMPT,
                provider=provider,
                max_tokens=400,
                temperature=0.2,
            )
            judged += 1
            notes.append(res.text or "")
    return EvalResult(total=total, judged=judged, notes=notes)

