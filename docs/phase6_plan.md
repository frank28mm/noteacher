# Phase 6: Stability & Engineering Implementation Plan

## Goal
Address P0/P1 critical stability issues identified in the auditing report: memory leaks, lack of error handling, and hardcoded configurations.

## User Review Required
- **Timeout Management**: Will switch to `useRef` based timer tracking for robust cleanup.
- **Error Boundary**: Will implement a "Something went wrong" fallback UI.
- **Env**: Will use `import.meta.env.VITE_API_BASE_URL`.

## Proposed Changes

### 1. Fix Memory Leaks (`src/hooks/useJobPolling.ts`, `src/components/ui/Toast.tsx`)
- **useJobPolling**: Use `useEffect` cleanup to explicitly clear `timeoutRef.current`. Ensure `poll` function stops if unmounted.
- **Toast**: Use a `Map` or `Set` in a `ref` to track active dismiss timers and clear all on unmount.

### 2. Global Error Boundary (`src/components/ui/ErrorBoundary.tsx`)
- Create generic Class Component `ErrorBoundary` (React requirement for catch).
- Wraps `AppRouter` in `App.tsx`.
- Fallback UI: Neumorphic card showing "Oops, something went wrong".

### 3. Environment Configuration (`src/services/api.ts`)
- Replace `const API_BASE_URL = '/api/v1'` with `import.meta.env.VITE_API_BASE_URL || '/api/v1'`.
- Add `src/vite-env.d.ts` for type safety.

### 4. Upload Safety (`src/pages/Upload.tsx`)
- Introduce `useRef` for `isMounted` check (simplest fix for now).
- Or better: verify use of clean-up function in `useEffect` matches the async flow.

## Verification Plan
1.  **Memory Leak Test**: Rapidly mount/unmount components (trigger Toast, navigate away) and check console for React warnings.
2.  **Env Test**: Change `.env` and verify API calls go to new URL (mock).
3.  **Crash Test**: Intentionally throw error in a component to see Error Boundary.
