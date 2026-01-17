# Phase 5: Frontend Testing & Reliability Plan

## Goal
Establish a robust testing infrastructure for the frontend and implement critical unit/component tests to ensure stability.

## User Review Required
- **Tool Selection**: Using **Vitest** (fast, native Vite integration) and **React Testing Library** (standard for React components).
- **Scope**:
  - **Unit Tests**: Utility functions (`cn`), Custom Hooks (`useJobPolling`).
  - **Component Tests**: Key interactive components (`Toast`, `Knob`, `Result`).
  - **E2E Tests**: (Optional for now) potentially Cypress or Playwright later.

## Proposed Changes

### 1. Infrastructure Setup
- **Install Dependencies**:
  - `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`.
- **Configuration**:
  - Update `vite.config.ts` to include test config.
  - Create `vitest.setup.ts` for global mocks/styles.
- **Scripts**: Add `"test": "vitest"` and `"coverage": "vitest run --coverage"`.

### 2. Unit Tests (`src/__tests__/unit`)
- **Utils**: `lib/utils.test.ts` (test `cn` class merging).
- **Hooks**: `hooks/useJobPolling.test.ts` (mock timers and API calls to verify polling logic).

### 3. Component Tests (`src/__tests__/components`)
- **UI Components**:
  - `Toast.test.tsx`: Verify toast shows/hides.
  - `Knob.test.tsx`: Verify rotation and click events.
- **Page Logic**:
  - `Result.test.tsx`: Verify "Processing" vs "Done" state rendering (mocking API).

## Verification Plan
1.  **Run Tests**: Execute `npm run test` and ensure all pass.
2.  **Coverage**: Check coverage report for critical paths.
