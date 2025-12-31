from homework_agent.services.report_features import compute_report_features


def test_compute_report_features_counts_and_accuracy():
    attempts = [
        {
            "submission_id": "s1",
            "item_id": "q:1",
            "question_number": "1",
            "created_at": "2025-01-01T00:00:00Z",
            "verdict": "correct",
            "knowledge_tags_norm": ["Math", "Algebra"],
            "question_type": "calc",
            "difficulty": "1",
        },
        {
            "submission_id": "s1",
            "item_id": "q:2",
            "question_number": "2",
            "created_at": "2025-01-01T00:00:00Z",
            "verdict": "incorrect",
            "knowledge_tags_norm": ["Math", "Geometry"],
            "question_type": "proof",
            "difficulty": "hard",
        },
        {
            "submission_id": "s2",
            "item_id": "q:3",
            "question_number": "3",
            "created_at": "2025-01-02T00:00:00Z",
            "verdict": "uncertain",
            "knowledge_tags_norm": ["Math", "Geometry"],
            "question_type": "proof",
            "difficulty": "hard",
        },
    ]
    steps = [
        {
            "submission_id": "s1",
            "item_id": "q:2",
            "step_index": 2,
            "severity": "calculation",
            "diagnosis_codes": ["calculation_error"],
        }
    ]

    features = compute_report_features(
        user_id="u1",
        attempts=attempts,
        steps=steps,
        window={"since": "x", "until": "y", "subject": None},
        taxonomy_version="v0.1",
        classifier_version=None,
    )
    assert features["overall"]["sample_size"] == 3
    assert features["overall"]["correct"] == 1
    assert features["overall"]["incorrect"] == 1
    assert features["overall"]["uncertain"] == 1
    assert features["overall"]["accuracy"] == 1 / 3
    assert features["process_diagnosis"]["diagnosis_code_counts"]["calculation_error"] == 1

