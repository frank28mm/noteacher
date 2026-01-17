# Backend Implementation Gap Analysis Report
**Date:** 2026-01-11
**Status:** Verification Complete

## 1. Executive Summary
A comprehensive verification of the `homework_agent` backend codebase was conducted to ensure alignment with the "Project Implementation Report" (`docs/project_implementation_report_20260111.md`). 

**Key Findings:**
- ✅ **Async Grading**: Fully supported via `X-Force-Async` header.
- ✅ **Chat Memory**: Rehydration from `submission_id` is fully implemented.
- 🔴 **Report Trends**: The backend logic for generating time-series data (charts) is **missing**. Currently, it only calculates aggregate snapshots.
- 🟡 **Archive API**: A dedicated "Archive/Mastery" endpoint is missing, though the generic "Exclusion" API exists.

---

## 2. Detailed Verification Results

### 2.1 ✅ Async Grading Support
- **Requirement**: The frontend needs to force async processing for seamless UX (polling flow).
- **Verification**: `usage of X-Force-Async` in `api/grade.py`.
- **Finding**: The backend explicitly checks `X-Force-Async` header and forces "Redis Queue" or "Background Task" mode accordingly.
- **Status**: **Verified**.

### 2.2 ✅ Chat Context & Rehydration
- **Requirement**: When a user enters the "AI Tutor" for a specific question, the chat must restore history even if the ephemeral session is lost, using the `submission_id`.
- **Verification**: `api/chat.py` -> `_rehydrate_session_from_submission_or_abort`.
- **Finding**: The logic explicitly looks up the durable `submissions` record, reseeds the "Question Bank" (Mistakes/OCR), and creates a fresh session linked to that submission.
- **Status**: **Verified**.

### 2.3 🔴 Report Trend Analysis (Critical Gap)
- **Requirement**: The "Analysis Report" requires line charts showing performance trends over time (e.g., "Fluency Trend over 7 days"). 
- **Verification**: `services/report_features.py` -> `compute_report_features`.
- **Finding**: The current implementation aggregates *all* data within the requested window into a single scalar set (e.g., `accuracy: 0.8`). It **does not** output a time-series array (e.g., `[{day: '2026-01-01', acc: 0.8}, {day: '2026-01-02', acc: 0.9}]`).
- **Impact**: The frontend cannot render the "Fluency" or "Accuracy" trend charts as designed.
- **Recommendation**: Update `compute_report_features` to perform daily bucket aggregation and return a `trends` list.

### 2.4 🟡 Mistake Archiving / Mastery
- **Requirement**: "Mistake Detail" -> "OK (Mastered)" button must remove the item from the Mistake Book.
- **Verification**: `api/mistakes.py`.
- **Finding**: The `POST /mistakes/exclusions` endpoint exists, which prevents an item from appearing in lists. However, there is no distinct semantic for "Mastery" vs "Bad Data" other than the `reason` string.
- **Impact**: Functional, but semantically weak.
- **Recommendation**: Frontend should send `reason="mastered"` to the exclusion endpoint. Ideally, add a wrapper endpoint `POST /mistakes/{item_id}/archive` for clarity, but the current API is sufficient for Phase 1.

---

## 3. Action Plan (Backend)

To close these gaps before frontend integration:

1.  **[P0] Implement Trend Logic**: Modify `homework_agent/services/report_features.py` to calculate and return `daily_stats` (accuracy/count per day) in the report JSON.
2.  **[P1] Define Archive Convention**: Document that "Mastery" == `POST /exclusions` with `reason="mastered"` in `API_CONTRACT.md`.
