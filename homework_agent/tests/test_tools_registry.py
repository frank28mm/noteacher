from homework_agent.core.tools import get_default_tool_registry, load_default_tools


def test_verify_calculation_tool_registered():
    load_default_tools()
    registry = get_default_tool_registry()
    spec = registry.get("verify_calculation")
    assert spec is not None
    assert "numeric" in (spec.description or "")


def test_verify_calculation_tool_works():
    load_default_tools()
    registry = get_default_tool_registry()
    result = registry.call(
        "verify_calculation", {"expression": "(2+3)^2", "expected": "25"}
    )
    assert result.get("status") == "valid"
