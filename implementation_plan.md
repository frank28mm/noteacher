# Implementation Plan - Fix Timeouts, Restore Vision Text, and Optimize

## Goal Description
1. **Restore Vision Traceability**: Ensure `vision_raw_text` is in schema and returned by API.
2. **Fix Timeouts (P0)**: Solve Chat/Grade API timeouts by making backend LLM calls non-blocking.
3. **Fix Schema Error**: Add `Severity.MINOR`.
4. **Optimize Performance**: Add client-side image compression.

## Proposed Changes
1. **Models**: Update `schemas.py` (`vision_raw_text`, `Severity.MINOR/MEDIUM`).
2. **Routes**: Update `routes.py` (populate `vision_raw_text`, use `run_in_executor` for `.chat`).
3. **Client/UI**: 不再维护 `verify_full_workflow.py`，改为 Demo UI + Vision 调试 Tab；展示 `vision_raw_text`。

## Verification
在 Demo UI 中：
- Vision 调试 Tab：直接调用 qwen3/doubao，确认能拿到完整识别文本。
- 智能批改 Tab：确认 `/grade` 返回 `vision_raw_text`，判定覆盖每题（学生作答/标准答案/is_correct，选项题 student_choice/correct_choice，verdict 仅 correct/incorrect/uncertain，severity 仅 calculation/concept/format/unknown/medium/minor）。
