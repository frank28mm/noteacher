# Phase 4 Implementation Plan: Polish & Engagement

## Goal
Enhance the user experience by adding global notifications (`Toast`) and smooth transitions/loading states (`Skeleton`, `Framer Motion`).

## User Review Required
- **Toast Design**: Will use a "Glassmorphism" or "Neumorphism" floating capsule style at the top of the screen.
- **Transitions**: Will apply a subtle fade-in/slide-up effect to all main routes.

## Proposed Changes

### 1. Global Notification System (`src/components/ui/Toast.tsx` + Context)
- **Component**: `ToastContainer` and `ToastItem`.
  - Style: Floating capsule, backdrop blur, shadow-neu-flat.
  - Animation: Slide down from top.
- **Context**: `ToastContext` exposing `showToast(message, type)`.
- **Integration**: Wrap `App.tsx` with `ToastProvider`.

### 2. Loading States (`src/components/ui/Skeleton.tsx`)
- **Component**: `Skeleton` primitive with shimmering pulse effect (using CSS animation `animate-pulse`).
- **Usage**:
  - `DataArchive`: Skeleton for grid items while loading.
  - `History`: Skeleton rows.
  - `ReportDetail`: Skeleton for score circle and chart.

### 3. Page Transitions (`src/components/Layout/PageTransition.tsx`)
- **Library**: `framer-motion` (already installed).
- **Component**: `PageTransition` wrapper.
- **Usage**: Wrap page content in `AppRouter` or individual pages to animate key mounting.

## Verification Plan

### Manual Verification
1.  **Toast**:
    -   Trigger toast via console or temporary button.
    -   Verify auto-dismiss after 3s.
    -   Verify stacking (if multiple) or replacement.
2.  **Skeletons**:
    -   Temporarily force `loading=true` in `DataArchive` or `History`.
    -   Verify shimmy animation and layout matching.
3.  **Transitions**:
    -   Navigate between tabs (Home -> Data -> History).
    -   Verify smooth fade/slide effect.
