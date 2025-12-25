# Autonomous Grade Agent Test Report

## Scope
- Run the new autonomous agent pipeline via a local script (no demo UI).
- Use the provided local image file and record outcomes.

## Environment
- Project root: `/Users/frank/Documents/网页软件开发/作业检查大师`
- Script: `homework_agent/scripts/run_autonomous_grade.py`
- Image: `/Users/frank/Desktop/作业档案/数学/202511/1103/IMG_0699 copy.JPG`

## Unit Tests
Command:
```bash
source .venv/bin/activate
python -m pytest homework_agent/tests/test_autonomous_agent.py -v
```
Result: **6 passed**

## Script Runs (Local File)
### Attempt A (Doubao)
Command:
```bash
source .venv/bin/activate
PYTHONPATH="/Users/frank/Documents/网页软件开发/作业检查大师" \
AUTONOMOUS_AGENT_MAX_ITERATIONS=2 \
AUTONOMOUS_AGENT_MAX_TOKENS=1200 \
AUTONOMOUS_AGENT_TIMEOUT_SECONDS=120 \
python homework_agent/scripts/run_autonomous_grade.py \
  --image "/Users/frank/Desktop/作业档案/数学/202511/1103/IMG_0699 copy.JPG" \
  --subject math --vision-provider doubao --llm-provider ark \
  --max-side 1024 --jpeg-quality 80
```
Result:
- **TimeoutError** after ~193s (log: `autonomous_grade_failed`).
- No GradeResponse returned before timeout.

### Attempt B (Qwen3)
Command:
```bash
source .venv/bin/activate
PYTHONPATH="/Users/frank/Documents/网页软件开发/作业检查大师" \
AUTONOMOUS_AGENT_MAX_ITERATIONS=1 \
AUTONOMOUS_AGENT_MAX_TOKENS=600 \
AUTONOMOUS_AGENT_TIMEOUT_SECONDS=60 \
python homework_agent/scripts/run_autonomous_grade.py \
  --image "/Users/frank/Desktop/作业档案/数学/202511/1103/IMG_0699 copy.JPG" \
  --subject math --vision-provider qwen3 --llm-provider silicon \
  --max-side 768 --jpeg-quality 75
```
Result:
- **429 Rate limiting** reported by the model service.
- `autonomous_grade_failed` with `TimeoutError`.
- GradeResponse returned with `status=failed`.

## Notes / Observations
- The autonomous loop is functioning (events emitted) but long-running LLM calls can exceed timeout in local runs.
- Qwen3 run hit TPM rate limit; needs a lower-frequency test window or higher quota.
- For local file tests, the script downscales the image before encoding (to reduce image tokens).

## Next Actions
- If you want a successful local run on this machine, we can:
  1) Lower concurrency and request frequency to avoid TPM limit,
  2) Increase timeout only for Aggregator step or reduce loops to 1,
  3) Confirm Supabase slice upload succeeds so the Aggregator uses slice URLs instead of base64.
