## Summary

- What changed:
- Why:

## Verification (Required)

- [ ] `python3 -m pytest -q`
- [ ] `python3 scripts/check_observability.py`
- [ ] `python3 -m bandit -r homework_agent -c bandit.yaml -x homework_agent/demo_ui.py -q`

## Replay / Metrics (When behavior changes)

- [ ] Replay cases updated/added (if prompt/agent/tool/threshold behavior changed)
- [ ] `python3 -m pytest homework_agent/tests/test_replay.py -v`
- [ ] `python3 scripts/collect_replay_metrics.py --output qa_metrics/metrics.json`

## Baseline updates (Only when justified)

If this PR updates `.github/baselines/*.json`:
- [ ] Explain why baseline needs update (expected behavior change vs regression)
- [ ] Attach `qa_metrics/report.html` + `qa_metrics/metrics_summary.json` and link to PR run
- [ ] Confirm rollback plan if online metrics degrade
