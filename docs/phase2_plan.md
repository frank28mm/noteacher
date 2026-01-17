# Phase 2 Implementation Plan: Data & History

## Goal
Implement the **Data Archive** (`src/pages/DataArchive.tsx`) and **History** (`src/pages/History.tsx`) modules based on `frontend_design_spec_v2.md` and `frontend_ui_page_code.md`.

## User Review Required
- **Mock Data**: Initial implementation will use static mock data.
- **"OK" Action**: The "OK" button in the Mistake Panel moves items to "Mastered".

## Proposed Changes

### 1. Data Archive (`src/pages/DataArchive.tsx`)
- **State Management**:
  - `view`: 'dashboard' | 'category_list'
  - `subject`: 'math' | 'english'
  - `selectedArchiveType`: 'mistake' | 'mastered' (Matches the "OK" button context)
  - `categoryFilter`: 'all' | 'review' | 'mastered'
- **Components**:
  - `SubjectGrid`: Displays the counts for each category (Algebra, Geometry, etc.).
  - `CategoryList`: Displays the list of questions when a subject is clicked.
  - `SegmentedSwitch`: For toggling Math/English and All/Review/Mastered.

### 2. History (`src/pages/History.tsx`)
- **Structure**:
  - List of past grading jobs.
  - Each item displays: ID (`#12345`), Date, Subject, Page Count.
- **Components**:
  - `HistoryItemCard`: Neumorphic card for each record.
  - `FilterPopup`: Simple modal for filtering (date/subject).

## Verification Plan
1.  **Data Archive**:
    -   Verify "Math / English" toggle switches content.
    -   Click "Algebra" card -> Should navigate to Category List view.
2.  **History**:
    -   Verify list shows `#` IDs.
