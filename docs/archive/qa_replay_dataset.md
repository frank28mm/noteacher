# QA Replay Dataset Structure

This document defines the structure for preparing a local replay dataset (10-20 samples) for Autonomous Agent validation and confidence threshold calibration.

## Dataset Format

Each replay sample is a JSON file containing input images and expected outputs for validation.

### Sample JSON Structure

```json
{
  "sample_id": "sample_001",
  "description": "Simple arithmetic problem - 1+1",
  "subject": "math",
  "expected_verdict": "correct",
  "expected_questions": 1,
  "input": {
    "image_urls": ["https://example.com/test_images/001.jpg"],
    "or_base64": "data:image/jpeg;base64,..."
  },
  "expected_output": {
    "ocr_text_should_contain": ["1+1", "=", "2"],
    "results": [
      {
        "question_number": "1",
        "verdict": "correct",
        "question_content": "1+1",
        "student_answer": "2",
        "reason": "正确",
        "judgment_basis": [
          "依据来源：题干",
          "观察：题目为1+1，学生答2",
          "规则：1+1=2",
          "结论：答案正确"
        ]
      }
    ],
    "summary": "第1题：正确",
    "expected_warnings": []
  },
  "metadata": {
    "difficulty": "easy",
    "category": "arithmetic",
    "requires_diagram_slice": false,
    "requires_math_verify": false,
    "min_confidence_threshold": 0.90
  }
}
```

## Recommended Sample Categories

### 1. Simple Arithmetic (3-5 samples)
- Pure calculation, no diagrams
- Expected: single iteration, confidence >= 0.95

```json
{
  "sample_id": "sample_001",
  "description": "Simple addition: 15 + 27",
  "subject": "math",
  "expected_verdict": "correct",
  "expected_iterations": 1,
  "metadata": {
    "difficulty": "easy",
    "category": "arithmetic",
    "min_confidence_threshold": 0.95
  }
}
```

### 2. Algebra Problems (3-5 samples)
- Multi-step equations
- May benefit from math_verify tool

```json
{
  "sample_id": "sample_005",
  "description": "Solve 2x + 5 = 13",
  "subject": "math",
  "expected_verdict": "correct",
  "expected_iterations": 1,
  "metadata": {
    "difficulty": "medium",
    "category": "algebra",
    "requires_math_verify": true,
    "min_confidence_threshold": 0.90
  }
}
```

### 3. Geometry with Diagrams (3-5 samples)
- Requires diagram_slice
- Tests figure/question separation

```json
{
  "sample_id": "sample_010",
  "description": "Angle relationship problem with diagram",
  "subject": "math",
  "expected_verdict": "incorrect",
  "expected_iterations": 2,
  "metadata": {
    "difficulty": "medium",
    "category": "geometry",
    "requires_diagram_slice": true,
    "min_confidence_threshold": 0.85
  },
  "expected_output": {
    "results": [
      {
        "question_number": "9",
        "verdict": "incorrect",
        "question_content": "判断∠2和∠BCD是什么关系",
        "student_answer": "同位角",
        "judgment_basis": [
          "依据来源：图示+题干",
          "观察：∠2 在 DC 左侧，∠BCD 在 DC 右侧",
          "规则：两角在截线两侧且在被截线之间 → 内错角",
          "结论：学生误用同位角"
        ]
      }
    ]
  }
}
```

### 4. Poor OCR Quality (2-3 samples)
- Tests ocr_fallback tool
- May result in uncertain verdict

```json
{
  "sample_id": "sample_015",
  "description": "Blurry image with partial OCR failure",
  "subject": "math",
  "expected_verdict": "uncertain",
  "expected_iterations": 2,
  "metadata": {
    "difficulty": "hard",
    "category": "ocr_quality",
    "requires_ocr_fallback": true,
    "min_confidence_threshold": 0.75
  },
  "expected_output": {
    "results": [
      {
        "question_number": "11",
        "verdict": "uncertain",
        "question_content": "计算 [无法识别] × 7",
        "student_answer": "[无法识别]",
        "warnings": ["OCR质量不足，建议人工复核"]
      }
    ]
  }
}
```

### 5. Multi-Question Pages (2-3 samples)
- Tests qindex_fetch and batching
- Multiple questions on single image

```json
{
  "sample_id": "sample_018",
  "description": "4 questions on one page (9-12)",
  "subject": "math",
  "expected_verdict": "mixed",
  "expected_iterations": 1,
  "metadata": {
    "difficulty": "medium",
    "category": "multi_question",
    "question_count": 4,
    "min_confidence_threshold": 0.88
  }
}
```

## Dataset Directory Structure

```
homework_agent/
├── tests/
│   ├── replay_data/
│   │   ├── samples/
│   │   │   ├── sample_001_simple_arithmetic.json
│   │   │   ├── sample_002_simple_arithmetic.json
│   │   │   ├── ...
│   │   │   ├── sample_020_multi_question.json
│   │   │   └── images/
│   │   │       ├── 001.jpg
│   │   │       ├── 002.jpg
│   │   │       └── ...
│   │   └── README.md
```

## Validation Script Template

```python
"""
Run Autonomous Agent on replay dataset and collect metrics.
"""
from pathlib import Path
import json
import asyncio
from homework_agent.services.autonomous_agent import run_autonomous_grade_agent
from homework_agent.models.schemas import ImageRef, Subject

async def run_replay_sample(sample_path: Path):
    """Run a single replay sample and validate results."""
    with open(sample_path) as f:
        sample = json.load(f)

    # Run agent
    result = await run_autonomous_grade_agent(
        images=[ImageRef(url=sample["input"]["image_urls"][0])],
        subject=Subject(sample["subject"]),
        provider="ark",
        session_id=f"replay_{sample['sample_id']}",
        request_id=f"req_{sample['sample_id']}",
    )

    # Validate
    assert result.status == "done"
    assert len(result.results) == sample["expected_questions"]

    for actual, expected in zip(result.results, sample["expected_output"]["results"]):
        assert actual["verdict"] == expected["verdict"]
        # Additional validations...

    return {
        "sample_id": sample["sample_id"],
        "passed": True,
        "iterations": result.iterations,
    }

# Run all samples
samples_dir = Path("tests/replay_data/samples")
results = []
for sample_file in samples_dir.glob("sample_*.json"):
    result = asyncio.run(run_replay_sample(sample_file))
    results.append(result)

# Report
print(f"Total samples: {len(results)}")
print(f"Passed: {sum(1 for r in results if r['passed'])}")
print(f"Average iterations: {sum(r['iterations'] for r in results) / len(results)}")
```

## Metrics to Record

For each sample, record:

| Metric | Description |
|--------|-------------|
| `status` | Pass/Fail |
| `iterations` | Actual Loop iterations |
| `confidence_values` | Per-iteration confidence scores |
| `duration_ms` | Total execution time |
| `verdict_match` | Expected vs actual verdict |
| `judgment_basis_quality` | Manual quality score (1-5) |
| `warnings` | Any warnings generated |

## Calibration Target

After running all samples, analyze:

1. **Confidence Distribution**: Are scores calibrated correctly?
2. **Iteration Count**: Average iterations < 2?
3. **Accuracy**: % of samples with correct verdict
4. **Uncertain Rate**: % of samples flagged as uncertain
5. **P50/P95 Latency**: Within acceptable bounds?

Adjust `confidence_threshold` if:
- Too many iterations (average > 2) → Lower threshold slightly
- Too many uncertain errors → Lower threshold
- High error rate → Raise threshold to require more evidence
