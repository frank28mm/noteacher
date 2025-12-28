"""
Telemetry collection for Autonomous Agent calibration.

Collects confidence distribution, loop iterations, and latency metrics
for threshold calibration and performance monitoring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from homework_agent.utils.cache import get_cache_store

logger = logging.getLogger(__name__)

TELEMETRY_TTL_SECONDS = 7 * 24 * 3600  # 7 days
TELEMETRY_KEY_PREFIX = "telemetry:autonomous:"


@dataclass
class LoopIterationTelemetry:
    """Telemetry data for a single Loop iteration."""

    session_id: str
    request_id: Optional[str]
    iteration: int
    timestamp: float
    planner_duration_ms: int
    executor_duration_ms: int
    reflector_duration_ms: int
    reflection_pass: bool
    reflection_confidence: float
    reflection_issues: List[str]
    plan_steps: int
    tools_called: List[str]


@dataclass
class AutonomousAgentTelemetry:
    """Complete telemetry data for an Autonomous Agent run."""

    session_id: str
    request_id: Optional[str]
    subject: str
    provider: str
    started_at: float
    completed_at: float
    total_duration_ms: int
    total_iterations: int
    exit_reason: str  # "confidence_threshold", "max_iterations", "error"
    iterations: List[LoopIterationTelemetry] = field(default_factory=list)
    aggregator_duration_ms: Optional[int] = None
    result_count: int = 0
    correct_count: int = 0
    incorrect_count: int = 0
    uncertain_count: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "request_id": self.request_id,
            "subject": self.subject,
            "provider": self.provider,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration_ms": self.total_duration_ms,
            "total_iterations": self.total_iterations,
            "exit_reason": self.exit_reason,
            "iterations": [
                it.to_dict() if hasattr(it, "to_dict") else it for it in self.iterations
            ],
            "aggregator_duration_ms": self.aggregator_duration_ms,
            "result_count": self.result_count,
            "correct_count": self.correct_count,
            "incorrect_count": self.incorrect_count,
            "uncertain_count": self.uncertain_count,
            "warnings": self.warnings,
        }


class TelemetryCollector:
    """Collects and stores telemetry data for calibration."""

    def __init__(self):
        self._cache = get_cache_store()

    def _key(self, session_id: str) -> str:
        return f"{TELEMETRY_KEY_PREFIX}{session_id}"

    def record_run(self, telemetry: AutonomousAgentTelemetry) -> None:
        """Store telemetry for a single run."""
        key = self._key(telemetry.session_id)
        self._cache.set(key, telemetry.to_dict(), ttl_seconds=TELEMETRY_TTL_SECONDS)

    def get_run(self, session_id: str) -> Optional[AutonomousAgentTelemetry]:
        """Retrieve telemetry for a specific run."""
        data = self._cache.get(self._key(session_id))
        if not isinstance(data, dict):
            return None
        iterations = data.get("iterations") or []
        iter_objs = []
        for it in iterations:
            if isinstance(it, dict):
                iter_objs.append(
                    LoopIterationTelemetry(
                        session_id=it.get("session_id", ""),
                        request_id=it.get("request_id"),
                        iteration=it.get("iteration", 0),
                        timestamp=it.get("timestamp", 0),
                        planner_duration_ms=it.get("planner_duration_ms", 0),
                        executor_duration_ms=it.get("executor_duration_ms", 0),
                        reflector_duration_ms=it.get("reflector_duration_ms", 0),
                        reflection_pass=it.get("reflection_pass", False),
                        reflection_confidence=it.get("reflection_confidence", 0.0),
                        reflection_issues=it.get("reflection_issues") or [],
                        plan_steps=it.get("plan_steps", 0),
                        tools_called=it.get("tools_called") or [],
                    )
                )
        return AutonomousAgentTelemetry(
            session_id=data.get("session_id", ""),
            request_id=data.get("request_id"),
            subject=data.get("subject", ""),
            provider=data.get("provider", ""),
            started_at=data.get("started_at", 0),
            completed_at=data.get("completed_at", 0),
            total_duration_ms=data.get("total_duration_ms", 0),
            total_iterations=data.get("total_iterations", 0),
            exit_reason=data.get("exit_reason", ""),
            iterations=iter_objs,
            aggregator_duration_ms=data.get("aggregator_duration_ms"),
            result_count=data.get("result_count", 0),
            correct_count=data.get("correct_count", 0),
            incorrect_count=data.get("incorrect_count", 0),
            uncertain_count=data.get("uncertain_count", 0),
            warnings=data.get("warnings") or [],
        )

    def get_recent_runs(self, limit: int = 100) -> List[AutonomousAgentTelemetry]:
        """
        Get recent runs for analysis.

        Note: This is a simplified implementation. In production,
        you'd want a proper index or separate storage for queries.
        """
        # For cache-based storage, we return an empty list
        # Implement proper querying if you switch to a dedicated telemetry store
        logger.warning("get_recent_runs not fully implemented for cache storage")
        return []


class TelemetryAnalyzer:
    """Analyzes telemetry data for calibration insights."""

    @staticmethod
    def calculate_confidence_distribution(
        telemetries: List[AutonomousAgentTelemetry],
    ) -> Dict[str, Any]:
        """Calculate confidence distribution across all iterations."""
        all_confidences = []
        pass_confidences = []
        fail_confidences = []

        for t in telemetries:
            for it in t.iterations:
                all_confidences.append(it.reflection_confidence)
                if it.reflection_pass:
                    pass_confidences.append(it.reflection_confidence)
                else:
                    fail_confidences.append(it.reflection_confidence)

        if not all_confidences:
            return {"error": "no_data"}

        def pct(arr, p):
            if not arr:
                return 0.0
            sorted_arr = sorted(arr)
            idx = int(len(sorted_arr) * p / 100)
            return sorted_arr[min(idx, len(sorted_arr) - 1)]

        return {
            "total_samples": len(all_confidences),
            "overall": {
                "min": min(all_confidences),
                "max": max(all_confidences),
                "mean": sum(all_confidences) / len(all_confidences),
                "p50": pct(all_confidences, 50),
                "p75": pct(all_confidences, 75),
                "p90": pct(all_confidences, 90),
                "p95": pct(all_confidences, 95),
            },
            "pass": {
                "count": len(pass_confidences),
                "mean": (
                    sum(pass_confidences) / len(pass_confidences)
                    if pass_confidences
                    else 0.0
                ),
                "p50": pct(pass_confidences, 50) if pass_confidences else 0.0,
            },
            "fail": {
                "count": len(fail_confidences),
                "mean": (
                    sum(fail_confidences) / len(fail_confidences)
                    if fail_confidences
                    else 0.0
                ),
                "p50": pct(fail_confidences, 50) if fail_confidences else 0.0,
            },
        }

    @staticmethod
    def calculate_iteration_distribution(
        telemetries: List[AutonomousAgentTelemetry],
    ) -> Dict[str, Any]:
        """Calculate Loop iteration distribution."""
        iterations = [t.total_iterations for t in telemetries]
        if not iterations:
            return {"error": "no_data"}

        def count_if(pred):
            return sum(1 for i in iterations if pred(i))

        return {
            "total_runs": len(iterations),
            "min_iterations": min(iterations),
            "max_iterations": max(iterations),
            "mean_iterations": sum(iterations) / len(iterations),
            "median_iterations": sorted(iterations)[len(iterations) // 2],
            "distribution": {
                "1_iteration": count_if(lambda x: x == 1),
                "2_iterations": count_if(lambda x: x == 2),
                "3_iterations": count_if(lambda x: x == 3),
                "4_plus_iterations": count_if(lambda x: x >= 4),
            },
        }

    @staticmethod
    def calculate_latency_percentiles(
        telemetries: List[AutonomousAgentTelemetry],
    ) -> Dict[str, Any]:
        """Calculate P50/P95 latency metrics."""
        total_durations = [t.total_duration_ms for t in telemetries]
        if not total_durations:
            return {"error": "no_data"}

        sorted_durations = sorted(total_durations)
        p50_idx = int(len(sorted_durations) * 0.5)
        p95_idx = int(len(sorted_durations) * 0.95)
        p99_idx = int(len(sorted_durations) * 0.99)

        return {
            "total_runs": len(total_durations),
            "p50_ms": sorted_durations[p50_idx],
            "p75_ms": sorted_durations[int(len(sorted_durations) * 0.75)],
            "p90_ms": sorted_durations[int(len(sorted_durations) * 0.90)],
            "p95_ms": sorted_durations[min(p95_idx, len(sorted_durations) - 1)],
            "p99_ms": sorted_durations[min(p99_idx, len(sorted_durations) - 1)],
            "min_ms": min(total_durations),
            "max_ms": max(total_durations),
            "mean_ms": sum(total_durations) / len(total_durations),
        }

    @staticmethod
    def generate_calibration_report(
        telemetries: List[AutonomousAgentTelemetry],
    ) -> Dict[str, Any]:
        """Generate comprehensive calibration report."""
        return {
            "generated_at": datetime.now().isoformat(),
            "total_runs": len(telemetries),
            "confidence_distribution": TelemetryAnalyzer.calculate_confidence_distribution(
                telemetries
            ),
            "iteration_distribution": TelemetryAnalyzer.calculate_iteration_distribution(
                telemetries
            ),
            "latency_percentiles": TelemetryAnalyzer.calculate_latency_percentiles(
                telemetries
            ),
            "threshold_suggestions": TelemetryAnalyzer._suggest_thresholds(telemetries),
        }

    @staticmethod
    def _suggest_thresholds(
        telemetries: List[AutonomousAgentTelemetry],
    ) -> Dict[str, Any]:
        """Suggest confidence threshold based on data."""
        all_confidences = []
        for t in telemetries:
            for it in t.iterations:
                all_confidences.append(it.reflection_confidence)

        if not all_confidences:
            return {"error": "no_data"}

        sorted_conf = sorted(all_confidences)
        p90 = sorted_conf[int(len(sorted_conf) * 0.90)]
        p75 = sorted_conf[int(len(sorted_conf) * 0.75)]

        return {
            "current_threshold": 0.90,
            "suggested_threshold": round(p90, 2),
            "p75_value": round(p75, 2),
            "note": "Consider setting threshold to p90 value to ensure high-quality exits",
        }


# Global collector instance
_collector: Optional[TelemetryCollector] = None


def get_telemetry_collector() -> TelemetryCollector:
    global _collector
    if _collector is None:
        _collector = TelemetryCollector()
    return _collector
