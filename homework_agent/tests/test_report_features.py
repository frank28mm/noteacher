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
    assert (
        features["process_diagnosis"]["diagnosis_code_counts"]["calculation_error"] == 1
    )
    assert "coverage" in features
    assert "cause_distribution" in features
    assert "trends" in features
    assert "meta" in features


def test_compute_report_features_trends_submission_granularity():
    attempts = [
        {
            "submission_id": "s1",
            "item_id": "q:1",
            "created_at": "2026-01-01T00:00:00Z",
            "verdict": "incorrect",
            "knowledge_tags_norm": ["K1"],
            "severity": "calculation",
            "question_type": "calc",
            "difficulty": "easy",
        },
        {
            "submission_id": "s1",
            "item_id": "q:2",
            "created_at": "2026-01-01T00:00:00Z",
            "verdict": "correct",
            "knowledge_tags_norm": ["K2"],
            "severity": "concept",
            "question_type": "calc",
            "difficulty": "easy",
        },
        {
            "submission_id": "s2",
            "item_id": "q:3",
            "created_at": "2026-01-03T00:00:00Z",
            "verdict": "uncertain",
            "knowledge_tags_norm": ["K1", "K2"],
            "severity": "concept",
            "question_type": "proof",
            "difficulty": "hard",
        },
    ]
    features = compute_report_features(
        user_id="u1",
        attempts=attempts,
        steps=[],
        window={"since": "2026-01-01T00:00:00Z", "until": "2026-01-04T00:00:00Z"},
        taxonomy_version=None,
        classifier_version=None,
    )
    trends = features["trends"]
    assert trends["granularity"] == "submission"
    assert trends["selected_knowledge_tags"][:2] == ["K1", "K2"]
    assert trends["selected_causes"][0] in {"calculation", "concept"}
    assert len(trends["points"]) == 2
    p1 = trends["points"][0]
    assert p1["point_key"] == "s1"
    assert p1["knowledge_top5"]["K1"] == 1
    assert p1["knowledge_top5"]["K2"] == 0


def test_compute_report_features_trends_bucket_3d():
    attempts = []
    # 16 distinct submissions -> triggers bucket_3d (count > 15)
    for i in range(16):
        attempts.append(
            {
                "submission_id": f"s{i:02d}",
                "item_id": f"q:{i}",
                "created_at": f"2026-01-{i+1:02d}T00:00:00Z",
                "verdict": "incorrect",
                "knowledge_tags_norm": ["K1"],
                "severity": "calculation",
                "question_type": "calc",
                "difficulty": "easy",
            }
        )

    features = compute_report_features(
        user_id="u1",
        attempts=attempts,
        steps=[],
        window={"since": "2026-01-01T00:00:00Z", "until": "2026-02-01T00:00:00Z"},
        taxonomy_version=None,
        classifier_version=None,
    )
    trends = features["trends"]
    assert trends["granularity"] == "bucket_3d"
    assert trends["selected_knowledge_tags"] == ["K1"]
    assert trends["selected_causes"] == ["calculation"]
    # 16 days -> 6 buckets (1-3,4-6,7-9,10-12,13-15,16-18)
    assert len(trends["points"]) == 6
    assert trends["points"][0]["knowledge_top5"]["K1"] == 3
    assert trends["points"][-1]["knowledge_top5"]["K1"] == 1


def test_compute_report_features_cause_distribution_wrongish_only_and_infer():
    attempts = [
        {
            "submission_id": "s1",
            "item_id": "q:1",
            "created_at": "2026-01-01T00:00:00Z",
            "verdict": "correct",
            # Missing severity for correct items should not pollute "错因统计".
        },
        {
            "submission_id": "s1",
            "item_id": "q:2",
            "created_at": "2026-01-01T00:00:00Z",
            "verdict": "incorrect",
            # Missing severity, but question_raw.reason provides a derivable hint.
            "question_raw": {"reason": "计算过程有移项错误，符号处理不当"},
        },
        {
            "submission_id": "s2",
            "item_id": "q:3",
            "created_at": "2026-01-02T00:00:00Z",
            "verdict": "uncertain",
            # Missing severity and no hint -> unknown.
            "question_raw": {"reason": "图片不清，无法判定"},
        },
    ]
    features = compute_report_features(
        user_id="u1",
        attempts=attempts,
        steps=[],
        window={"since": "2026-01-01T00:00:00Z", "until": "2026-01-03T00:00:00Z"},
        taxonomy_version=None,
        classifier_version=None,
    )
    cd = features["cause_distribution"]
    assert cd["sample_size"] == 2
    assert cd["severity_counts"]["calculation"] == 1
    assert cd["severity_counts"]["unknown"] == 1
