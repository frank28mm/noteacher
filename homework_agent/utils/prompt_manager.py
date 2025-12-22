from __future__ import annotations

import os
from typing import Any, Dict

import yaml
from jinja2 import Template


class PromptManager:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _load(self, name: str) -> Dict[str, Any]:
        if name in self._cache:
            return self._cache[name]
        path = os.path.join(self.base_dir, name)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._cache[name] = data
        return data

    def render(self, name: str, **kwargs: Any) -> str:
        data = self._load(name)
        template = data.get("template") or data.get("prompt") or ""
        if not template:
            return ""
        return Template(template).render(**kwargs)


def get_prompt_manager() -> PromptManager:
    base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
    return PromptManager(base_dir)

