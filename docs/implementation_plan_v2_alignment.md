# Implementation Plan - Frontend Logic Alignment (Spec V2)

This plan details the changes required to strictly align the frontend interaction logic with `docs/frontend_design_spec_v2.md`, addressing the user's feedback on missing "Scan-to-Learn" flows and improper state handling.

## User Review Required

> [!IMPORTANT]
> **API Dependency**: The plan assumes the backend supports `POST /api/v1/uploads` and `POST /api/v1/grade` as distinct steps, and `GET /api/v1/jobs/{job_id}` returns specific fields (`done_pages`, `total_pages`, `question_cards`). I will mock strictly against these spec definitions.

## Proposed Changes

### 1. Scan-to-Learn Flow (Upload -> Grade -> Result)

#### [MODIFY] [Upload.tsx](file:///Users/frank/Documents/网页软件开发/作业检查大师/homework_frontend/src/pages/Upload.tsx)
- **Current**: Uploads file -> Simulates progress -> Navigates to Result.
- **Spec**:
    1. `POST /api/v1/uploads` -> Receive `upload_id`.
    2. `POST /api/v1/grade` (with `upload_id`) -> Receive `job_id`.
    3. **Immediately** navigate to `Result.tsx?jobId={job_id}`.
- **Change**: Remove simulated progress bar. Implement the 2-step API call. Redirect immediately.

#### [MODIFY] [Result.tsx](file:///Users/frank/Documents/网页软件开发/作业检查大师/homework_frontend/src/pages/Result.tsx)
- **Current**: Assumes `status === 'done'` to show content.
- **Spec**: "Progressive Disclosure". Shows Page 1 as soon as it's ready while Page 2 processes.
- **Change**:
    - Use `useJobPolling` to listen to job updates.
    - Render `question_cards` as they arrive in the data, even if `status !== 'done'`.
    - Show "Analyzing..." placeholders for pending pages.
    - Implement "Questions List" (horizontally scrollable) that fills up dynamically.

### 2. Home Page "Task in Progress" State

#### [MODIFY] [Home.tsx](file:///Users/frank/Documents/网页软件开发/作业检查大师/homework_frontend/src/pages/Home.tsx)
- **Current**: Static dashboard.
- **Spec**: If a job is running, Home must show "Task in Progress" state with progress stats.
- **Change**:
    - Check `localStorage` for `active_job_id`.
    - If active, poll (lightly) or check status.
    - Replace central "Tap to Scan" with "Processing... X/Y Pages Done".

### 3. Data Archive "Mastered" Action

#### [MODIFY] [DataArchive.tsx](file:///Users/frank/Documents/网页软件开发/作业检查大师/homework_frontend/src/pages/DataArchive.tsx)
- **Current**: Visual-only "OK" button.
- **Spec**: Clicking "OK" irreversibly moves item to "Mastered".
- **Change**: Implement local state update (mock) to visually move the card from "Review" list to "Mastered" list upon clicking "OK".

## Verification Plan

### Automated Tests
- None planned for UI logic (manual verification is prioritized for visual flows).

### Manual Verification
1. **Scan Flow**:
   - Go to `Camera` -> Take Photo -> `Upload`.
   - Click `Upload`. Verify immediate jump to `Result`.
   - In `Result`, verify "Loading/Analyzing" state is shown initially, then cards appear.
2. **Home State**:
   - While `Result` is loading, click `Home`.
   - Verify Home shows "Processing..." instead of "Tap to Scan".
3. **Data Archive**:
   - Go to `Data`.
   - Click "OK" on a card.
   - Verify card disappears or moves to "Mastered" view/style.
