from __future__ import annotations

import os
from typing import Any, Dict

import yaml
from jinja2 import Template


class PromptManager:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _resolve_name(self, name: str, *, variant: str | None) -> str:
        """
        Resolve a prompt filename with an optional variant.

        Convention:
        - base: `foo.yaml`
        - variant: `foo__B.yaml`
        """
        base = str(name or "").strip()
        v = (variant or "").strip()
        if not base or not v:
            return base
        if base.endswith(".yaml"):
            candidate = base[: -len(".yaml")] + f"__{v}.yaml"
        else:
            candidate = base + f"__{v}"
        path = os.path.join(self.base_dir, candidate)
        if os.path.exists(path):
            return candidate
        return base

    def _load(self, name: str, *, variant: str | None = None) -> Dict[str, Any]:
        resolved = self._resolve_name(name, variant=variant)
        if resolved in self._cache:
            return self._cache[resolved]
        path = os.path.join(self.base_dir, resolved)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._cache[resolved] = data
        return data

    def render(self, name: str, *, variant: str | None = None, **kwargs: Any) -> str:
        data = self._load(name, variant=variant)
        template = data.get("template") or data.get("prompt") or ""
        if not template:
            return ""
        return Template(template).render(**kwargs)

    def meta(self, name: str, *, variant: str | None = None) -> Dict[str, Any]:
        data = self._load(name, variant=variant)
        # Only expose small, stable fields.
        return {
            "id": data.get("id"),
            "version": data.get("version"),
            "language": data.get("language"),
            "purpose": data.get("purpose"),
            "variant": (variant or "").strip() or None,
        }


def get_prompt_manager() -> PromptManager:
    base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
    return PromptManager(base_dir)
