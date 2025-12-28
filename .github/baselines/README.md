# Baselines

This folder stores versioned baseline JSON files for offline regression checks (e.g. `scripts/check_baseline.py`).

Bootstrap:
- Generate current summary: `python3 homework_agent/scripts/collect_metrics.py ...`
- Refresh baseline: `python3 scripts/check_baseline.py --current qa_metrics/metrics_summary.json --baseline .github/baselines/metrics_baseline.json --update-baseline`

In CI, you can start with `--allow-missing-baseline` and only enforce hard gating once the baseline is committed and stable.
