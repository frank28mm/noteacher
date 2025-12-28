"""
Test telemetry collection and analysis.
"""

from __future__ import annotations

from homework_agent.utils.telemetry import (
    LoopIterationTelemetry,
    AutonomousAgentTelemetry,
    TelemetryAnalyzer,
)


def test_confidence_distribution_calculation():
    """Test confidence distribution analysis."""
    telemetries = [
        AutonomousAgentTelemetry(
            session_id="s1",
            request_id="r1",
            subject="math",
            provider="ark",
            started_at=0,
            completed_at=1000,
            total_duration_ms=5000,
            total_iterations=2,
            exit_reason="confidence_threshold",
            iterations=[
                LoopIterationTelemetry(
                    session_id="s1",
                    request_id="r1",
                    iteration=1,
                    timestamp=0,
                    planner_duration_ms=100,
                    executor_duration_ms=50,
                    reflector_duration_ms=100,
                    reflection_pass=True,
                    reflection_confidence=0.92,
                    reflection_issues=[],
                    plan_steps=0,
                    tools_called=[],
                ),
                LoopIterationTelemetry(
                    session_id="s1",
                    request_id="r1",
                    iteration=2,
                    timestamp=0,
                    planner_duration_ms=100,
                    executor_duration_ms=50,
                    reflector_duration_ms=100,
                    reflection_pass=False,
                    reflection_confidence=0.75,
                    reflection_issues=["low confidence"],
                    plan_steps=1,
                    tools_called=["ocr_fallback"],
                ),
            ],
            result_count=1,
            correct_count=1,
            incorrect_count=0,
            uncertain_count=0,
        ),
    ]

    dist = TelemetryAnalyzer.calculate_confidence_distribution(telemetries)

    assert dist["total_samples"] == 2
    assert dist["overall"]["mean"] == 0.835  # (0.92 + 0.75) / 2
    assert dist["overall"]["min"] == 0.75
    assert dist["overall"]["max"] == 0.92
    assert dist["pass"]["count"] == 1
    assert dist["pass"]["mean"] == 0.92
    assert dist["fail"]["count"] == 1
    assert dist["fail"]["mean"] == 0.75


def test_iteration_distribution_calculation():
    """Test iteration distribution analysis."""
    telemetries = [
        AutonomousAgentTelemetry(
            session_id=f"s{i}",
            request_id="r1",
            subject="math",
            provider="ark",
            started_at=0,
            completed_at=1000,
            total_duration_ms=5000,
            total_iterations=it,
            exit_reason="confidence_threshold",
            iterations=[],
            result_count=1,
            correct_count=1,
            incorrect_count=0,
            uncertain_count=0,
        )
        for i, it in enumerate([1, 1, 2, 2, 3, 3])
    ]

    dist = TelemetryAnalyzer.calculate_iteration_distribution(telemetries)

    assert dist["total_runs"] == 6
    assert dist["min_iterations"] == 1
    assert dist["max_iterations"] == 3
    assert dist["mean_iterations"] == 2.0
    assert dist["distribution"]["1_iteration"] == 2
    assert dist["distribution"]["2_iterations"] == 2
    assert dist["distribution"]["3_iterations"] == 2


def test_latency_percentiles_calculation():
    """Test P50/P95 latency calculation."""
    telemetries = [
        AutonomousAgentTelemetry(
            session_id=f"s{i}",
            request_id="r1",
            subject="math",
            provider="ark",
            started_at=0,
            completed_at=1000,
            total_duration_ms=ms,
            total_iterations=1,
            exit_reason="confidence_threshold",
            iterations=[],
            result_count=1,
            correct_count=1,
            incorrect_count=0,
            uncertain_count=0,
        )
        for i, ms in enumerate(
            [5000, 10000, 15000, 20000, 25000, 30000, 35000, 40000, 45000, 50000]
        )
    ]

    percentiles = TelemetryAnalyzer.calculate_latency_percentiles(telemetries)

    assert percentiles["total_runs"] == 10
    assert percentiles["p50_ms"] == 30000  # median of 10 items at index 5
    assert percentiles["p95_ms"] == 50000  # 95th percentile of 10 items
    assert percentiles["min_ms"] == 5000
    assert percentiles["max_ms"] == 50000


def test_calibration_report_generation():
    """Test comprehensive calibration report."""
    telemetries = [
        AutonomousAgentTelemetry(
            session_id="s1",
            request_id="r1",
            subject="math",
            provider="ark",
            started_at=0,
            completed_at=5000,
            total_duration_ms=5000,
            total_iterations=1,
            exit_reason="confidence_threshold",
            iterations=[
                LoopIterationTelemetry(
                    session_id="s1",
                    request_id="r1",
                    iteration=1,
                    timestamp=0,
                    planner_duration_ms=100,
                    executor_duration_ms=50,
                    reflector_duration_ms=100,
                    reflection_pass=True,
                    reflection_confidence=0.95,
                    reflection_issues=[],
                    plan_steps=0,
                    tools_called=[],
                )
            ],
            result_count=1,
            correct_count=1,
            incorrect_count=0,
            uncertain_count=0,
        )
    ]

    report = TelemetryAnalyzer.generate_calibration_report(telemetries)

    assert "generated_at" in report
    assert report["total_runs"] == 1
    assert "confidence_distribution" in report
    assert "iteration_distribution" in report
    assert "latency_percentiles" in report
    assert "threshold_suggestions" in report
    assert report["threshold_suggestions"]["current_threshold"] == 0.90
