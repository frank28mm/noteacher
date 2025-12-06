# Implementation Plan - Phase 1: Agent Core

## Goal
Build the "Brain" of the Homework Master. A standalone Python Microservice (FastAPI) capable of inputting homework images and outputting graded notifications with Socratic guidance.

## User Review Required
> [!IMPORTANT]
> **API Key Required**: This phase requires a valid OpenAI-compatible API Key (GPT-4o or Claude 3.5 Sonnet recommended for Vision). Please ensure `.env` file is configured.

## Proposed Changes

### 1. Environment & Scaffold
#### [NEW] `homework_agent/`
*   Initialize Python project with `poetry` or `venv`.
*   Dependencies: `fastapi`, `uvicorn`, `langchain`, `openai`, `pydantic`, `python-dotenv`.
*   Setup `.env` template.

### 2. Data Model & Interface Contract (Partner 1 Recommendation)
#### [NEW] `homework_agent/schemas.py`
*   Define **Pydantic Models** to serve as the strict contract between Node BFF and Python Agent.
*   `GradeRequest`: `images` (List[str]), `subject` (Enum).
*   `GradeResponse`: `wrong_items` (List[WrongItem]), `summary`.
*   `WrongItem`: `box_2d` (List[int]), `reason`, `standard_answer` (optional), `knowledge_tags` (List[str]).
*   `ChatRequest`: `history` (List[Message]), `question`.

### 3. Core Logic (The Brain)
#### [NEW] `homework_agent/core/ocr.py`
*   Implement `OCRProcessor` to handle handwritten text recognition (Vision API).

#### [NEW] `homework_agent/core/grader.py`
*   Implement `HomeworkGrader` class.
*   **Math Chain**:
    *   Prompt engineering for Step-by-step verification.
    *   Geometry auxiliary line check (Text description).
*   **English Chain**:
    *   Prompt engineering for Semantic Similarity (Strict Mode threshold > 0.9).
*   **Socratic Tutor**:
    *   Logic for generating hints vs full explanation (Counter < 5).
    *   **Memory Boundary**: Ensure strictly session-based context (no long-term memory leakage).

### 4. API Layer
#### [NEW] `homework_agent/main.py`
*   `POST /grade`: Accepts `GradeRequest`, returns `GradeResponse`.
*   `POST /chat`: Accepts `ChatRequest`, returns SSE stream.

### 4. Verification UI (Temporary)
#### [NEW] `homework_agent/demo_ui.py`
*   Simple **Gradio** interface to drag-and-drop images and test the Agent interactively without waiting for the Mobile App.

## Verification Plan

### Automated Tests
*   **Unit Tests**: `pytest` for Prompt logic.
    *   Input: Sample math image (from `tests/data`).
    *   Expect: JSON containing "step error" detected.
*   **Integration Tests**: Test FastAPI endpoints.

### Manual Verification
1.  Run `python homework_agent/demo_ui.py`.
2.  **Math Case**: Upload a math worksheet with a calculation error. Verify Agent describes the error step.
3.  **English Case**: Upload an English fill-in-the-blank. Write a synonym answer. Verify Agent accepts it (Semantic Similarity).
4.  **Chat Case**: Ask "Why?" on a wrong question. Verify Agent gives a Hint, not the answer.
