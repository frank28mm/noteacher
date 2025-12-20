# Refactoring God Functions: perform_grading & chat_stream

## Background

These two functions previously exceeded 800 LOC each and had severe coupling.
They have now been refactored to orchestration-only (<100 LOC) with extracted stage modules.

This implementation plan outlines an incremental, test-verified refactoring approach.

## Current Status (2025-12-17)

- ✅ `perform_grading` is **73 LOC** (orchestration only)
- ✅ `chat_stream` is **78 LOC** (orchestration only)
- ✅ Stage modules landed:
  - `homework_agent/api/_grading_stages.py`
  - `homework_agent/api/_chat_stages.py`
- ✅ Shared helpers split:
  - `homework_agent/utils/url_image_helpers.py`
  - `homework_agent/utils/supabase_image_proxy.py`
- ✅ Unified errors:
  - `homework_agent/utils/errors.py` (HTTP JSON + SSE error payload)
- ✅ Test gate: `pytest` **86 passed**

---

## User Review Required

> [!IMPORTANT]
> This refactoring is large and may introduce regressions. Each phase includes verification before proceeding.

> [!WARNING]
> Nested functions inside these "god functions" rely on closure variables (e.g., `req`, `session_for_ctx`, `vision_result`). We will pass these explicitly to extracted functions.

---

## Goals & Non-Goals

### Goals
- Reduce `perform_grading` and `chat_stream` to **orchestration-only** (< 100 LOC each).
- Improve debuggability by eliminating silent failures (no more `except Exception: pass` in hot paths).
- Increase testability by extracting stage functions with explicit inputs/outputs and injectable dependencies.
- Preserve API behavior (wire compatibility) and user-visible UX flows.

### Non-Goals (for this refactor)
- Changing external API contract fields, response shapes, or endpoint semantics.
- Large-scale architecture rewrite (e.g., replacing Redis/Supabase choices).
- Performance tuning beyond “no regression”; optimization can come after stability.

---

## Guiding Principles (How We Refactor Safely)

1. **Extract-in-place first, move later**
   - Step 1: extract private helpers inside the same module (e.g., `_run_vision_stage` inside `grade.py`).
   - Step 2: once stable and well-tested, move helpers into dedicated modules.
   - This avoids circular imports and reduces risk per step.

2. **Context holds state, but dependencies are explicit**
   - Context objects (`GradingContext`, `ChatContext`) hold state that evolves across stages.
   - External dependencies (clients/stores/settings/time) are passed explicitly or attached to the context as a “deps” object.

3. **Stage outputs are “mergeable patches”, not ad-hoc tuples**
   - Stages should return structured outcomes that can be merged, logged, and tested.
   - Prefer small dict-like patches (`meta_patch`, `timings_patch`) over growing positional tuples.

4. **Best-effort is OK, silent failure is not**
   - If something is non-critical: catch, log (structured), proceed.
   - If something is critical to correctness: raise and surface an error response.

---

## Baseline (Current Repo Facts)

- Largest files: `homework_agent/api/chat.py` (~1289 LOC), `homework_agent/api/grade.py` (~906 LOC)
- Test suite: **86 tests collected** (includes `spec_*.py` via `pytest.ini`)
- Stage modules: `homework_agent/api/_grading_stages.py` (~596 LOC), `homework_agent/api/_chat_stages.py` (~647 LOC)

---

## Phase 1: Refactor `perform_grading` (grade.py)

### Current Structure Analysis

The function has 5 logical stages:
1. **Initialize** (lines 332-387): Setup session, settings, timings, meta
2. **Vision Stage** (lines 388-779): Primary vision call, fallback handling
3. **LLM Grading Stage** (lines 780-1090): Math/English grading with fallbacks
4. **Result Post-Processing** (lines 1091-1157): Build question bank, compute counts
5. **Return Result** (lines 1158-1200): Construct final GradeResponse

### Proposed Changes

#### Proposed module placement

`perform_grading` is API orchestration with I/O (cache, storage, external providers). The extracted stages should initially live close to the API layer:

- Start with in-file private helpers in `homework_agent/api/grade.py`
- Then move to `homework_agent/api/_grading_stages.py` (or `homework_agent/services/grading/*` if we later split by provider)

Avoid placing these in `homework_agent/core/*` until the stage functions are pure / domain-level.

#### [NEW] `_grading_stages` module (after stabilization)

New module to house extracted stage functions:

```python
# homework_agent/api/_grading_stages.py

@dataclass
class StageOutcome:
    meta_patch: Dict[str, Any]
    timings_patch: Dict[str, int]
    warnings: List[str]
    artifacts: Dict[str, Any]  # e.g. proxy urls, raw provider responses (redacted), etc.

async def run_vision_stage(...) -> StageOutcome:
    """Execute vision analysis with fallback handling."""
    
async def run_llm_grading_stage(...) -> StageOutcome:
    """Execute LLM grading for math or english."""
    
def build_grade_response(...) -> GradeResponse:
    """Construct final grading response with all metadata."""
```

#### [MODIFY] grade.py

Refactor `perform_grading` to orchestrate extracted stages:

```python
async def perform_grading(req: GradeRequest, provider_str: str) -> GradeResponse:
    ctx = GradingContext(req=req, provider_str=provider_str, deps=GradingDeps(...))
    
    vision_out = await run_vision_stage(ctx)
    ctx.apply(vision_out)
    
    llm_out = await run_llm_grading_stage(ctx)
    ctx.apply(llm_out)
    
    return build_grade_response(ctx)
```

#### Suggested `GradingContext` / deps shape (minimal)

The goal is to make stages testable without importing the whole FastAPI module graph.

- `GradingContext`
  - inputs: `req`, `provider_str`, `session_id`, `user_id`
  - derived: `settings`, `started_at`, `timings_ms`, `meta`, `warnings`
  - artifacts: `page_image_urls`, `proxy_page_image_urls`, `vision_raw_text`, `qbank`, `grade_result`
- `GradingDeps` (injectable)
  - `vision_client`, `llm_client`
  - `cache_store` / session store functions
  - `submission_store` (Supabase)
  - `now_fn` / `monotonic_fn` (for deterministic tests)

#### Error-handling rule for Phase 1

Replace patterns like:

```python
try: ...
except Exception:
    pass
```

with:

```python
except Exception as e:
    log_event(logger, "...", level="warning", error=str(e), session_id=..., request_id=...)
```

If a stage cannot proceed (e.g., no images and no upload record), raise a structured error and let the endpoint return a deterministic failure.

---

## Phase 2: Refactor `chat_stream` (chat.py)

### Current Structure Analysis

The function has 6 logical stages:
1. **Initialize** (lines 786-860): Session lookup, validation, logging
2. **Context Binding** (lines 861-1070): Resolve focus question, qbank, qindex
3. **Visual Path** (lines 1130-1345): Handle image slices, mandatory visual checks
4. **Corrections** (lines 1346-1400): Capture user corrections for OCR errors
5. **Cached Visual Facts** (lines 1400-1470): Read cached VFE outputs and gate usage
6. **LLM Streaming** (lines 1470-1604): Producer-consumer pattern for SSE

### Proposed Changes

#### Proposed module placement

`chat_stream` is tightly coupled to SSE streaming, session cache, qindex, and cached visual facts. Similar to grading:

- Start with in-file private helpers in `homework_agent/api/chat.py`
- Then move to `homework_agent/api/_chat_stages.py`

Keep truly pure helpers (string parsing, routing heuristics) where they already live, and add unit tests around them.

#### [NEW] `_chat_stages` module (after stabilization)

New module for extracted functions:

```python
# homework_agent/api/_chat_stages.py

def initialize_chat_session(...) -> Tuple[Dict, str, bool]:
    """Initialize or restore chat session."""
    
def resolve_chat_context(...) -> Dict[str, Any]:
    """Bind focus question and construct wrong_item_context."""
    
async def ensure_slices(...) -> EnsureSlicesOutcome:
    """Ensure qindex slices exist (enqueue + wait + DB fallback)."""

async def read_cached_visual_facts(...) -> VisualFactsOutcome:
    """Read cached visual facts from qbank/session (no real-time vision)."""

async def handle_visual_path(...) -> Optional[bytes]:
    """Product requirement: no real-time vision in chat; if cached facts missing, still answer with warning."""
    
def stream_llm_response(...) -> AsyncIterator[bytes]:
    """Producer-consumer LLM streaming."""
```

#### [MODIFY] chat.py

Refactor `chat_stream` to orchestrate stages:

```python
async def chat_stream(req, request, last_event_id) -> AsyncIterator[bytes]:
    session_data, session_id, is_new = initialize_chat_session(...)
    
    context = resolve_chat_context(session_data, req)
    
    visual_response = await handle_visual_path(req, context)
    if visual_response:
        yield visual_response; return
    
    async for chunk in stream_llm_response(context, req):
        yield chunk
```

#### Suggested `ChatContext` / deps shape (minimal)

- `ChatContext`
  - inputs: `req`, `session_id`, `user_id`, `request_id`
  - session state: `session_data`, `history`, `interaction_count`, `focus_question_number`
  - resolved: `qbank`, `qindex`, `wrong_item_context`, `focus_question`
  - visual artifacts: `visual_facts`, `vfe_gate`, `image_refs`
- `ChatDeps` (injectable)
  - cache/session store
  - submission store (DB fallback for slices)
  - qindex queue interface
  - (no vision client in chat; VFE runs async after slices)
  - llm client
  - time functions

#### Product requirement guardrails to preserve (must not regress)

- If user explicitly requests looking at the image/diagram (or uses dispute terms like 同位角/内错角/位置关系/看图):
  - Use cached `visual_facts` only.
  - If missing: **explicitly tell the user “未读图/信息不足”，and do not guess.**

---

## Verification Plan

### Automated Tests

All existing tests must pass before and after each phase:

```bash
# Run full test suite
python -m pytest homework_agent/tests/ -v --tb=short
```

Current baseline: **60 tests collected** (and should pass on the current mainline).

### Unit Tests to Add

#### Phase 1 (Grade Refactoring)

New test file: `homework_agent/tests/test_grading_stages.py`
- Tests for `run_vision_stage` (mock vision client)
- Tests for `run_llm_grading_stage` (mock LLM client)
- Tests for `build_grade_response` (pure function)

#### Phase 2 (Chat Refactoring)

New test file: `homework_agent/tests/test_chat_stages.py`
- Tests for `initialize_chat_session`
- Tests for `resolve_chat_context`
- Tests for `handle_visual_path`

### Contract / Canary Tests (recommended)

These are “cheap integration checks” that prevent silent regressions in streaming behavior:

- `test_chat_sse_sequence_contract`
  - Given a fixed session with cached qbank/qindex, assert SSE event order and termination:
    - at least one `chat` event
    - optional `heartbeat`
    - a final `done` event
  - Assert `retry_after_ms` behavior on “waiting slices” path (if applicable).

- `test_chat_fail_closed_when_visual_required`
- When user asks “看图/位置关系/同位角内错角” and no cached visual facts available:
    - response must contain a clear “看不到图/无法判断位置关系”
    - must not contain “结合图形/从图形来看”这类不实表述

### Integration Verification

After each phase, verify manually:

1. **Grade API Test**: Call /grade endpoint with test image
2. **Chat API Test**: Call /chat endpoint with test session

---

## Error Handling & Observability Checklist (P0 quality bar)

When extracting stages, apply these rules in the touched code blocks:

- Replace `except Exception: pass` with `except Exception as e: log_event(... level="warning" ...)`
- Include correlation keys in logs when available:
  - `request_id`, `session_id`, `user_id`, `submission_id`
- If the failure is expected/benign, log a stable reason:
  - e.g., `reason="redis_unavailable"`, `reason="ocr_disabled"`, `reason="slice_expired"`
- Never log secrets (keys/tokens); redact URLs with sensitive query params.

---

## Implementation Order

| Order | Task | Risk | Verification |
|-------|------|------|--------------|
| 0 | Add canary SSE tests (no refactor) | Low | Full suite |
| 1 | Extract `GradingContext` + `GradingDeps` | Low | Unit tests |
| 2 | Extract in-file `_run_vision_stage` | Medium | Full suite + manual |
| 3 | Extract in-file `_run_llm_stage` | Medium | Full suite + manual |
| 4 | Extract `build_grade_response` (pure) | Low | Unit tests |
| 5 | Simplify `perform_grading` | Low | Full suite |
| 6 | (Optional) Move helpers to `_grading_stages.py` | Medium | Full suite |
| 7 | Extract `ChatContext` + `ChatDeps` | Low | Unit tests |
| 8 | Extract in-file `_initialize_chat_session` | Low | Full suite |
| 9 | Extract in-file `_resolve_chat_context` | Medium | Full suite |
| 10 | Split visual into `_ensure_slices` + `read_cached_visual_facts` | High | Full suite + manual |
| 11 | Simplify `chat_stream` | Low | Full suite |
| 12 | (Optional) Move helpers to `_chat_stages.py` | Medium | Full suite |
| 13 | Remove `WARNING DEBUG` logs once stable | Low | Full suite |

---

## Success Criteria

- [ ] `perform_grading` reduced to < 100 lines (orchestration only)
- [ ] `chat_stream` reduced to < 100 lines (orchestration only)
- [ ] All existing tests passing (60 collected as of this plan)
- [ ] New unit tests for extracted functions (target: 20+ new tests)
- [ ] New canary tests for SSE + “fail closed on visual” behavior
- [ ] No regression in API behavior
