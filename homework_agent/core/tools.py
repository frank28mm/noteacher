from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    func: Callable[..., Any]
    requires_confirmation: bool = False
    confirmation_type: Optional[str] = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not spec or not spec.name:
            raise ValueError("ToolSpec.name is required")
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_specs(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def openai_tools(self) -> List[Dict[str, Any]]:
        tools = []
        for spec in self.list_specs():
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.parameters,
                    },
                }
            )
        return tools

    def call(
        self,
        name: str,
        args: Dict[str, Any],
        *,
        progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
        confirmation: Optional[bool] = None,
    ) -> Any:
        spec = self.get(name)
        if not spec:
            raise ValueError(f"Tool not found: {name}")
        if spec.requires_confirmation and confirmation is not True:
            return {
                "status": "confirmation_required",
                "tool": name,
                "message": "该工具需要确认后才能执行",
            }

        fn = spec.func
        sig = inspect.signature(fn)
        kwargs = dict(args or {})
        if progress_cb and "progress_cb" in sig.parameters:
            kwargs["progress_cb"] = progress_cb

        if inspect.iscoroutinefunction(fn):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                # Best-effort: run in a new loop to avoid blocking.
                new_loop = asyncio.new_event_loop()
                try:
                    return new_loop.run_until_complete(fn(**kwargs))
                finally:
                    new_loop.close()
            return asyncio.run(fn(**kwargs))
        return fn(**kwargs)


_DEFAULT_REGISTRY = ToolRegistry()


def tool(
    *,
    name: str,
    description: str,
    parameters: Dict[str, Any],
    requires_confirmation: bool = False,
    confirmation_type: Optional[str] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            func=fn,
            requires_confirmation=requires_confirmation,
            confirmation_type=confirmation_type,
        )
        _DEFAULT_REGISTRY.register(spec)
        return fn

    return decorator


def get_default_tool_registry() -> ToolRegistry:
    return _DEFAULT_REGISTRY


def load_default_tools() -> None:
    """Best-effort: import tools package to register built-ins."""
    try:
        import homework_agent.tools  # noqa: F401
    except Exception as e:
        logger.debug(f"Loading default tools failed: {e}")

