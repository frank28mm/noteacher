"""
Real image integration test for Autonomous Agent.

Tests with actual homework image from Supabase storage.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from homework_agent.models.schemas import ImageRef, Subject
from homework_agent.services.autonomous_agent import run_autonomous_grade_agent


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get("RUN_REAL_IMAGE_TESTS") != "1",
    reason="set RUN_REAL_IMAGE_TESTS=1 to run",
)
async def test_real_image_autonomous_agent():
    """Test Autonomous Agent with real homework image."""
    image_url = "https://uitcnddxrnyfflhwmket.supabase.co/storage/v1/object/public/homework-test-staging/users/dev_user/uploads/upl_5c8a2a507cb04c1e/f4960df749cf47b9beb314b6dd7d3212.jpg"

    print(f"\n{'='*60}")
    print("Testing Autonomous Agent with real image")
    print(f"URL: {image_url}")
    print(f"{'='*60}\n")

    result = await run_autonomous_grade_agent(
        images=[ImageRef(url=image_url)],
        subject=Subject.MATH,
        provider="ark",  # Using Ark (Doubao)
        session_id="test_real_image_001",
        request_id="test_req_001",
    )

    print(f"\n{'='*60}")
    print("RESULT SUMMARY")
    print(f"{'='*60}")
    print(f"Status: {result.status}")
    print(f"Iterations: {result.iterations}")
    print(f"OCR Text: {result.ocr_text[:200] if result.ocr_text else 'None'}...")
    print(f"Total Questions: {len(result.results) if result.results else 0}")
    print(f"Correct: {sum(1 for r in result.results if r.get('verdict') == 'correct')}")
    print(
        f"Incorrect: {sum(1 for r in result.results if r.get('verdict') == 'incorrect')}"
    )
    print(
        f"Uncertain: {sum(1 for r in result.results if r.get('verdict') == 'uncertain')}"
    )
    print(f"Summary: {result.summary}")
    print(f"Warnings: {result.warnings}")

    # Detailed results
    if result.results:
        print(f"\n{'='*60}")
        print("DETAILED RESULTS")
        print(f"{'='*60}")
        for i, item in enumerate(result.results, 1):
            print(f"\n--- Question {i} ---")
            print(f"Number: {item.get('question_number', 'N/A')}")
            print(f"Verdict: {item.get('verdict', 'N/A')}")
            print(f"Question: {item.get('question_content', 'N/A')[:100]}...")
            print(f"Answer: {item.get('student_answer', 'N/A')[:100]}...")
            print(f"Reason: {item.get('reason', 'N/A')[:100]}...")
            jb = item.get("judgment_basis", [])
            if jb:
                print("Judgment Basis:")
                for line in jb:
                    print(f"  - {line}")
            if item.get("warnings"):
                print(f"Warnings: {item.get('warnings')}")

    return result


if __name__ == "__main__":
    result = asyncio.run(test_real_image_autonomous_agent())
