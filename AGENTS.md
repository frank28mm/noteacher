# AGENTS.md - AI Agent Development Guide

> **Project**: Homework Checker Agent (作业检查大师)
> **Stack**: Python 3.10+ / FastAPI / Redis / Supabase / LLM (Doubao/Qwen3)

---

## 1. Build / Lint / Test Commands

### Install Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # includes requirements.txt + dev tools
```

### Run Backend Server
```bash
export PYTHONPATH=$(pwd)
uvicorn homework_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

### Run Workers (require Redis)
```bash
python3 -m homework_agent.workers.qindex_worker    # OCR/bbox processing
python3 -m homework_agent.workers.grade_worker     # Async grading
python3 -m homework_agent.workers.facts_worker     # Facts extraction
python3 -m homework_agent.workers.report_worker    # Report generation
```

### Testing
```bash
# Run all tests
pytest -q

# Run single test file
pytest homework_agent/tests/test_routes.py -v

# Run single test function
pytest homework_agent/tests/test_routes.py::test_grade_stub -v

# Run tests matching pattern
pytest -k "test_chat" -v

# Run with markers
pytest -m integration -v              # integration tests only
pytest -m "not integration" -v        # skip integration tests
```

### Linting & Security
```bash
ruff check homework_agent             # Fast linter
black homework_agent --check          # Format check
pylint --disable=all --enable=E0602 homework_agent   # Undefined variables
bandit -r homework_agent -c bandit.yaml -x homework_agent/demo_ui.py -q
python3 scripts/check_no_secrets.py   # Secret hygiene
python3 scripts/check_observability.py --strict   # Observability rules
```

### Compile Check (syntax)
```bash
python3 -m compileall -q homework_agent
```

---

## 2. Project Structure

```
homework_agent/
├── main.py              # FastAPI entry point
├── api/                 # Route handlers (/grade, /chat, /uploads, etc.)
├── core/                # Business logic, prompts
├── models/              # Pydantic schemas (schemas.py = source of truth)
├── services/            # LLM/Vision clients, autonomous agent, queues
├── utils/               # Settings, observability, cache, errors
├── workers/             # Background workers (Redis-based)
├── tests/               # All tests (test_*.py, spec_*.py)
└── prompts/             # YAML prompt templates
```

**Key Files**:
- `homework_agent/API_CONTRACT.md` - API interface contract
- `homework_agent/models/schemas.py` - Pydantic models (field names/types)
- `docs/INDEX.md` - Documentation navigation
- `agent_sop.md` - Standard operating procedures

---

## 3. Code Style Guidelines

### Imports
```python
# Standard order: stdlib -> third-party -> local
import logging
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from homework_agent.utils.settings import get_settings
from homework_agent.utils.observability import log_event, trace_span
```

### Formatting
- **Formatter**: black (line length default 88)
- **Linter**: ruff + pylint (E0602 undefined variables)
- Use type hints for all function signatures
- Prefer `async def` for endpoints and external calls

### Naming Conventions
| Type | Convention | Example |
|------|------------|---------|
| Classes | PascalCase | `GradeRequest`, `VisionProvider` |
| Functions | snake_case | `grade_homework`, `get_settings` |
| Constants | UPPER_SNAKE | `MATH_GRADER_SYSTEM_PROMPT` |
| Files | snake_case | `autonomous_agent.py` |
| Tests | test_*.py or spec_*.py | `test_routes.py` |

### Type Hints
```python
# Required for all functions
async def grade_homework(
    *,
    images: List[ImageRef],
    subject: Subject,
    session_id: Optional[str] = None,
) -> GradeResponse:
    ...
```

### Error Handling
```python
# Use structured error responses
from homework_agent.utils.errors import build_error_payload, ErrorCode

# Never suppress errors silently
try:
    result = await some_operation()
except SomeError as e:
    logger.error("Operation failed", exc_info=True)
    raise HTTPException(status_code=500, detail=str(e))
```

---

## 4. Observability Requirements (P0)

### Tracing - All functions need @trace_span
```python
from homework_agent.utils.observability import trace_span

@trace_span("grade_homework")
async def grade_homework(...):
    ...
```

### Structured Logging - Use log_event()
```python
from homework_agent.utils.observability import log_event

# Required fields: session_id, request_id, iteration
log_event(logger, "agent_tool_call",
          session_id=session_id,
          request_id=request_id,
          iteration=iteration,
          tool=tool_name,
          status="running")
```

### LLM Usage Tracking
```python
from homework_agent.utils.observability import log_llm_usage

log_llm_usage(logger,
              request_id=request_id,
              session_id=session_id,
              model="doubao-pro-32k",
              provider="ark",
              usage=response.usage,
              stage="planner")
```

---

## 5. Architecture Constraints

### DO NOT
- Use Claude Agent SDK (use FastAPI + direct LLM/Vision API)
- Suppress type errors with `as any`, `@ts-ignore`
- Commit secrets or .env files
- Run heavy tasks (image processing) in API main process
- Read historical user profiles in chat context

### MUST
- Use normalized bbox `[ymin, xmin, ymax, xmax]` (origin top-left)
- Return `warnings` when bbox/slice unavailable
- Use Redis queues for async tasks (qindex, grade)
- Validate vision_provider against whitelist (doubao/qwen3 only)
- Include `judgment_basis` in Chinese for audit trail

### Idempotency
- Use `X-Idempotency-Key` header
- Conflict returns 409
- 24h key lifetime

### Sessions
- `session_id` scoped to 24h lifetime
- Chat only reads current submission context
- No cross-submission memory

---

## 6. Testing Patterns

### Unit Test Structure
```python
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from homework_agent.main import create_app

client = TestClient(create_app())

def test_grade_stub():
    with patch("homework_agent.api.grade.run_autonomous_grade_agent", 
               new_callable=AsyncMock) as mock:
        mock.return_value = mock_result
        resp = client.post("/api/v1/grade", json=payload)
    
    assert resp.status_code == 200
    assert "warnings" in resp.json()
```

### Test Markers
```python
@pytest.mark.integration   # Requires external services
@pytest.mark.replay        # Replay dataset tests
```

---

## 7. API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/uploads` | POST | Upload images (returns upload_id) |
| `/api/v1/grade` | POST | Grade homework (sync or async) |
| `/api/v1/chat` | POST | Socratic tutoring (SSE stream) |
| `/api/v1/jobs/{job_id}` | GET | Check async job status |
| `/api/v1/session/{session_id}/qbank` | GET | Get question bank |
| `/api/v1/reports` | GET/POST | Learning reports |
| `/metrics` | GET | Prometheus metrics |

---

## 8. Environment Variables

Key variables (see `.env.template` for full list):
```bash
ARK_API_KEY=...                    # Doubao/Ark API
SILICON_API_KEY=...                # SiliconFlow/Qwen3 API
REDIS_URL=redis://localhost:6379/0 # Required for workers
SUPABASE_URL=...                   # Storage
SUPABASE_KEY=...                   # Anon key
DEV_USER_ID=dev_user               # Dev fallback user
SLICE_TTL_SECONDS=86400            # 24h default
```

---

## 9. Pre-commit Checklist

- [ ] Fields match `API_CONTRACT.md` and `schemas.py`
- [ ] Normalized bbox validated [0,1]
- [ ] `@trace_span` on new functions
- [ ] `log_event()` with required fields
- [ ] Tests pass: `pytest -q`
- [ ] Lint passes: `ruff check homework_agent`
- [ ] No secrets: `python3 scripts/check_no_secrets.py`

---

## 10. CI Pipeline (GitHub Actions)

```yaml
# .github/workflows/ci.yml triggers on push/PR
jobs:
  test:
    - pip install -r requirements-dev.txt
    - pip check                           # Dependency sanity
    - python3 -m compileall -q homework_agent
    - pytest -q
    - python3 scripts/check_observability.py --strict
    - bandit -r homework_agent -c bandit.yaml
    - python3 scripts/check_no_secrets.py
    
  redis_integration:
    - pytest homework_agent/tests/test_*_redis_integration.py
```

---

## 11. Key Documentation

| Document | Purpose |
|----------|---------|
| `docs/INDEX.md` | Navigation hub (start here) |
| `homework_agent/API_CONTRACT.md` | API interface spec |
| `product_requirements.md` | Product requirements |
| `agent_sop.md` | Execution flow & SOP |
| `docs/development_rules.md` | Engineering rules |
| `docs/engineering_guidelines.md` | Development constraints |

---

**Last Updated**: 2026-01-11
