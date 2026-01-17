# Phase 3 Implementation Plan: Analysis & Reports

## Goal
Implement the **Analysis** module (`src/pages/Analysis.tsx`) and **Report** features (`src/pages/ReportDetail.tsx`) based on `frontend_design_spec_v2.md` and `frontend_ui_page_code.md`.
Features a unique "Knob Console" interface for the Analysis dashboard and detailed charts for reports.

## User Review Required
- **Mock Data**: Reports will be populated with static mock data initially.
- **Charts**: Will use standard HTML/CSS for simple charts (progress bars) and potentially a lightweight library like `recharts` if needed for complex graphs, or just pure CSS for neumorphic visuals as per UI code. The UI code uses pure HTML/CSS for neumorphic visualization, so I will stick to that to maintain the specific look without extra heavy dependencies if possible, or use simple SVG.

## Proposed Changes

### 1. Analysis Dashboard (`src/pages/Analysis.tsx`)
- **UI Structure**:
  - Two large "Knob" controls for Topic (Math/English) and Period (Week/Month).
  - A central "START" button to generate/view report.
  - Bottom navigation to Report History.
- **Interactions**:
  - Rotating knobs (visual feedback using CSS transforms).
  - "Start" navigates to `ReportDetail`.

### 2. Report Detail (`src/pages/ReportDetail.tsx`)
- **Header**: Score, Date, Student Name.
- **Sections**:
  - **Overview**: Big score circle, subject breakdown.
  - **Knowledge Map**: Grid of tags with strength indicators.
  - **Trend**: Simple bar/line chart (simulated with CSS for now).
  - **Action Items**: List of weak points to review.

### 3. Report History
- A simple list view similar to History but for generated reports. Can be part of `Analysis.tsx` or a separate path `/analysis/history`.
- Spec implies "Report History List" is accessible. I will add it as a sub-view or separate route.

## Verification Plan

### Manual Verification
1.  **Analysis Page**:
    -   Click Knobs -> Should rotate/toggle values (Math <-> English).
    -   Click Start -> Navigate to Report Detail.
2.  **Report Detail**:
    -   Verify visual fidelity of the score card and charts.
    -   Check "Back" navigation.
