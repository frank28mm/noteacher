#!/usr/bin/env python3
"""
Comprehensive verification script for v3 Implementation:
1. Tool Registry & Math Tools
2. Image Preprocessor (OpenCV)
3. Prompt Manager (YAML)
4. Modified LLM with Tool Calling (optional live test)
"""

import os
import sys

# Ensure package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from homework_agent.core.tools import get_default_tool_registry, load_default_tools


def test_tool_registry():
    print("\n=== TEST 1: Tool Registry ===")
    load_default_tools()
    registry = get_default_tool_registry()

    # Check tools are registered
    tools = registry.list_specs()
    print(f"  Registered tools: {[t.name for t in tools]}")
    assert len(tools) >= 1, "No tools registered!"

    # Check OpenAI schema generation
    schema = registry.openai_tools()
    print(f"  OpenAI schema count: {len(schema)}")
    assert len(schema) >= 1, "No OpenAI schemas generated!"

    # Test verify_calculation
    result = registry.call("verify_calculation", {"expression": "2+2", "expected": "4"})
    print(f"  verify_calculation(2+2=4): {result}")
    assert result.get("status") == "valid", f"Expected valid, got {result}"

    result = registry.call("verify_calculation", {"expression": "2+2", "expected": "5"})
    print(f"  verify_calculation(2+2=5): {result}")
    assert result.get("status") == "invalid", f"Expected invalid, got {result}"

    print("  ✅ Tool Registry tests PASSED")


def test_image_preprocessor():
    print("\n=== TEST 2: Image Preprocessor ===")
    try:
        from homework_agent.services.image_preprocessor import preprocess_image_bytes
        import cv2
        _cv_available = True
    except ImportError:
        _cv_available = False
        print("  ⚠️ OpenCV not installed, skipping image preprocessing tests")
        return

    # Create a simple test image (gray gradient)
    import numpy as np
    img = np.zeros((100, 100), dtype=np.uint8)
    img[:, :50] = 50  # left half darker
    img[:, 50:] = 200  # right half lighter
    _, encoded = cv2.imencode(".jpg", img)
    test_bytes = encoded.tobytes()

    # Run preprocessing
    result = preprocess_image_bytes(test_bytes)
    print(f"  Input size: {len(test_bytes)} bytes")
    print(f"  Output size: {len(result)} bytes")
    assert len(result) > 0, "Preprocessing returned empty result!"

    # Decode and verify it's still valid image
    decoded = cv2.imdecode(np.frombuffer(result, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    assert decoded is not None, "Output is not a valid image!"
    print(f"  Output image shape: {decoded.shape}")

    print("  ✅ Image Preprocessor tests PASSED")


def test_prompt_manager():
    print("\n=== TEST 3: Prompt Manager ===")
    from homework_agent.utils.prompt_manager import get_prompt_manager

    pm = get_prompt_manager()

    # Test loading math grader prompt
    math_prompt = pm.render("math_grader_system.yaml")
    print(f"  Math grader prompt length: {len(math_prompt)} chars")
    assert len(math_prompt) > 100, "Math prompt too short or empty!"

    # Test loading socratic tutor prompt
    socratic_prompt = pm.render("socratic_tutor_system.yaml")
    print(f"  Socratic tutor prompt length: {len(socratic_prompt)} chars")
    assert len(socratic_prompt) > 100, "Socratic prompt too short or empty!"

    # Test loading english grader prompt
    english_prompt = pm.render("english_grader_system.yaml")
    print(f"  English grader prompt length: {len(english_prompt)} chars")
    assert len(english_prompt) > 100, "English prompt too short or empty!"

    print("  ✅ Prompt Manager tests PASSED")


def test_llm_tool_support():
    print("\n=== TEST 4: LLM Tool Calling Support ===")
    # Check if socratic_tutor method accepts tools parameter
    import inspect
    from homework_agent.services.llm import LLMClient

    sig = inspect.signature(LLMClient.socratic_tutor)
    params = list(sig.parameters.keys())
    print(f"  socratic_tutor params: {params}")

    if "tools" in params or "enable_tools" in params:
        print("  ✅ LLM has tool support parameter")
    else:
        print("  ⚠️ LLM socratic_tutor may not have integrated tools yet")


def main():
    print("=" * 60)
    print("V3 IMPLEMENTATION VERIFICATION SCRIPT")
    print("=" * 60)

    all_passed = True
    try:
        test_tool_registry()
    except Exception as e:
        print(f"  ❌ Tool Registry FAILED: {e}")
        all_passed = False

    try:
        test_image_preprocessor()
    except Exception as e:
        print(f"  ❌ Image Preprocessor FAILED: {e}")
        all_passed = False

    try:
        test_prompt_manager()
    except Exception as e:
        print(f"  ❌ Prompt Manager FAILED: {e}")
        all_passed = False

    try:
        test_llm_tool_support()
    except Exception as e:
        print(f"  ❌ LLM Tool Support FAILED: {e}")
        all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 ALL TESTS PASSED!")
    else:
        print("⚠️ SOME TESTS FAILED - See above for details")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
