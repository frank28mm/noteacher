# Phase 6: Stability & Engineering Walkthrough

## Overview
This phase focused on "hardening" the frontend application against crashes, memory leaks, and configuration issues. No visible UI features were added, but the application is now significantly more robust.

## Key Improvements

### 1. Memory Leak Prevention
We refactored `useJobPolling` and `ToastProvider` to rigorously manage timers and async state.
- **useJobPolling**: Now uses `isMountedRef` to prevent state updates on unmounted components and clears timeouts in `useEffect` cleanup.
- **Toast**: Tracks all active timer IDs in a `ref` and clears them all when the provider unmounts.

### 2. Global Error Boundary
We added a React Error Boundary to catch unexpected crashes.
- Instead of a white screen, users now see a friendly "Something went wrong" card with a reload button.
- In development, it shows the stack trace.

### 3. Async Safety
The `Upload` page was prone to race conditions (e.g., navigating away while uploading).
- We implemented `isMountedRef` checks at every async step.
- We added `URL.revokeObjectURL` to prevent memory leaks from image previews.

### 4. Environment Configuration
- Replaced hardcoded `/api/v1` with `import.meta.env.VITE_API_BASE_URL`.
- Added TypeScript definitions for env variables.

## Verification
- ✅ **Build Success**: `npm run build` passes with zero type errors.
- ✅ **Tests**: `npm test` passes (5/5).
