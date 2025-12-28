from __future__ import annotations

import ast
import math
import re
from typing import Any, Dict

from homework_agent.core.tools import tool


_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Mod,
    ast.FloorDiv,
    ast.Constant,
    ast.Load,
    ast.Call,
    ast.Name,
)

_ALLOWED_FUNCS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
}


def _safe_eval(expr: str) -> float:
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError("unsupported_expression")
        if isinstance(node, ast.Call):
            if (
                not isinstance(node.func, ast.Name)
                or node.func.id not in _ALLOWED_FUNCS
            ):
                raise ValueError("unsupported_function")
        if isinstance(node, ast.Name) and node.id not in _ALLOWED_FUNCS:
            raise ValueError("variables_not_supported")
    compiled = compile(tree, "<expr>", "eval")
    return float(
        eval(  # nosec B307
            compiled,
            {"__builtins__": {}},
            dict(_ALLOWED_FUNCS),
        )
    )


@tool(
    name="verify_calculation",
    description="Check whether a numeric calculation is correct.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The expression to verify, e.g. '(2+3)^2'.",
            },
            "expected": {
                "type": "string",
                "description": "The expected numeric result, e.g. '25'.",
            },
        },
        "required": ["expression", "expected"],
    },
)
def verify_calculation(expression: str, expected: str) -> Dict[str, Any]:
    expr = str(expression or "").strip()
    exp = str(expected or "").strip()
    if not expr or not exp:
        return {
            "status": "invalid",
            "detail": "expression or expected missing",
        }

    if re.search(r"[A-Za-z]", expr) or re.search(r"[A-Za-z]", exp):
        return {
            "status": "unknown",
            "detail": "contains variables; numeric evaluation skipped",
        }

    expr_norm = expr.replace("^", "**")
    exp_norm = exp.replace("^", "**")
    try:
        expr_val = _safe_eval(expr_norm)
        exp_val = _safe_eval(exp_norm)
    except Exception as e:
        return {
            "status": "invalid",
            "detail": f"parse_error: {e}",
        }

    diff = abs(expr_val - exp_val)
    ok = diff <= 1e-6
    return {
        "status": "valid" if ok else "invalid",
        "expression": expr,
        "expected": exp,
        "computed": expr_val,
        "difference": diff,
    }
