from homework_agent.services.facts_extractor import extract_facts_from_grade_result


def test_extract_facts_from_grade_result_builds_attempts_and_steps():
    grade_result = {
        "subject": "math",
        "questions": [
            {
                "question_number": "1",
                "verdict": "correct",
                "knowledge_tags": ["Math", "Algebra"],
                "question_type": "calc",
                "difficulty": "2",
                "math_steps": [
                    {"index": 1, "verdict": "correct", "severity": "calculation"}
                ],
            },
            {
                "question_number": "2",
                "verdict": "incorrect",
                "knowledge_tags": ["Math", "Geometry"],
                "question_type": "proof",
                "difficulty": "hard",
                "math_steps": [
                    {"index": 1, "verdict": "correct", "severity": "calculation"},
                    {"index": 2, "verdict": "incorrect", "severity": "calculation"},
                    {"index": 3, "verdict": "incorrect", "severity": "BOGUS"},
                ],
            },
        ],
    }
    out = extract_facts_from_grade_result(
        user_id="u1",
        submission_id="s1",
        created_at="2025-01-01T00:00:00Z",
        subject="math",
        grade_result=grade_result,
    )
    assert len(out.question_attempts) == 2
    a1, a2 = out.question_attempts

    assert a1["item_id"] == "q:1"
    assert a1["question_idx"] == 1
    assert a1["verdict"] == "correct"
    assert a1["question_type"] == "calc"
    assert a1["difficulty"] == "2"
    # correct question: steps are omitted during normalize_questions
    assert a1["severity"] is None

    assert a2["item_id"] == "q:2"
    assert a2["question_idx"] == 2
    assert a2["verdict"] == "incorrect"
    assert a2["question_type"] == "proof"
    assert a2["difficulty"] == "hard"
    # derived from first non-correct step severity
    assert a2["severity"] == "calculation"

    # Only non-correct steps kept, bogus severity normalized to unknown
    assert len(out.question_steps) == 2
    step2 = next(s for s in out.question_steps if s["step_index"] == 2)
    step3 = next(s for s in out.question_steps if s["step_index"] == 3)
    assert step2["severity"] == "calculation"
    assert step2["diagnosis_codes"] == ["calculation_error"]
    assert step3["severity"] == "unknown"
