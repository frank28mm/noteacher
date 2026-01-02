#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCOPE = REPO_ROOT / "homework_agent"

# Avoid noisy warnings from parsing source files (e.g., invalid escape sequences).
warnings.filterwarnings("ignore", category=SyntaxWarning)


@dataclass(frozen=True)
class Finding:
    kind: str
    path: Path
    line: int
    message: str


def _iter_py_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        # Exclude caches/venv
        if any(part in {".venv", "__pycache__"} for part in path.parts):
            continue
        yield path


def _is_excluded(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT)
    # Allow prints in scripts/tests/demo utilities.
    if rel.parts[:2] in {("homework_agent", "tests"), ("homework_agent", "scripts")}:
        return True
    if rel.parts[:2] == ("homework_agent", "demo_ui.py"):
        return True
    return False


def _check_no_prints(scope: Path) -> List[Finding]:
    findings: List[Finding] = []
    for path in _iter_py_files(scope):
        if _is_excluded(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                findings.append(
                    Finding(
                        kind="print",
                        path=path,
                        line=getattr(node, "lineno", 1),
                        message="Avoid print() in production code; use log_event() or logger.",
                    )
                )
    return findings


def _call_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _check_log_event_keywords(scope: Path) -> Tuple[List[Finding], List[Finding]]:
    warn: List[Finding] = []
    err: List[Finding] = []
    for path in _iter_py_files(scope):
        if _is_excluded(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = _call_name(node.func)
            if fn != "log_event":
                continue
            keywords = {k.arg for k in node.keywords if isinstance(k, ast.keyword) and k.arg}
            # Heuristic:
            # - If a log_event includes session_id, we expect request_id for correlation.
            if "session_id" in keywords and "request_id" not in keywords:
                warn.append(
                    Finding(
                        kind="log_event_missing_request_id",
                        path=path,
                        line=getattr(node, "lineno", 1),
                        message="log_event has session_id but missing request_id (correlation may break).",
                    )
                )
            # - If log_event logs error without error_type, prefer including error_type.
            if "error" in keywords and "error_type" not in keywords:
                warn.append(
                    Finding(
                        kind="log_event_missing_error_type",
                        path=path,
                        line=getattr(node, "lineno", 1),
                        message="log_event has error but missing error_type (harder to aggregate).",
                    )
                )
    return warn, err


def main() -> int:
    parser = argparse.ArgumentParser(description="Lightweight observability checks (best-effort).")
    parser.add_argument(
        "--scope",
        type=str,
        default=str(DEFAULT_SCOPE),
        help="Directory to scan (default: homework_agent/)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail (exit 1) on warnings; default only prints warnings and exits 0.",
    )
    args = parser.parse_args()

    scope = Path(args.scope).resolve()
    if not scope.exists():
        print(f"[FAIL] scope not found: {scope}")
        return 2

    warnings: List[Finding] = []
    errors: List[Finding] = []

    warnings.extend(_check_no_prints(scope))
    w, e = _check_log_event_keywords(scope)
    warnings.extend(w)
    errors.extend(e)

    for f in errors:
        print(f"[ERROR] {f.kind} {f.path.relative_to(REPO_ROOT)}:{f.line} {f.message}")
    for f in warnings:
        print(f"[WARN]  {f.kind} {f.path.relative_to(REPO_ROOT)}:{f.line} {f.message}")

    if errors:
        print(f"\n[FAIL] observability check: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    if warnings and args.strict:
        print(f"\n[FAIL] observability check: {len(warnings)} warning(s) (strict mode)")
        return 1
    print(f"[OK] observability check: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
