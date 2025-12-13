# Implementation Plan - Fix Timeouts, Restore Vision Text, and Optimize

## Goal Description
1. **Restore Vision Traceability**: Ensure `vision_raw_text` is in schema and returned by API.
2. **Fix Timeouts (P0)**: Solve Chat/Grade API timeouts by making backend LLM calls non-blocking.
3. **Fix Schema Error**: Add `Severity.MINOR`.
4. **Optimize Performance**: Add client-side image compression.
5. **Socratic Chat Post-Grading Only**: 辅导仅在完成批改后使用，允许“全对”也可对话；取消 5 轮硬限制，仍保持苏格拉底不直接给答案。
6. **BBox + Slice（路线3）**: 采用传统 OCR/版面分析生成“整题区域 bbox（可多 bbox）”与切片 URL，支持 chat 精准聚焦与回看。

## Proposed Changes
1. **Models**: Update `schemas.py` (`vision_raw_text`, `Severity.MINOR/MEDIUM`).
2. **Routes**: Update `routes.py` (populate `vision_raw_text`, use `run_in_executor` for `.chat`).
3. **Client/UI**: 不再维护 `verify_full_workflow.py`，改为 Demo UI + Vision 调试 Tab；展示 `vision_raw_text`。
4. **Chat gating**: Demo UI 与后端均以批改 session 为前置，默认不做纯闲聊；苏格拉底对话无限轮，引导式回答，不直接给答案。
5. **Question Index Cache**: `/grade` 完成后，将“每道题”的索引快照写入 session（Redis），支持 chat 通过题号检索（不要求用户手动勾选错题）。
6. **BBox + Slice（OCR/Layout）**:
   - OCR 版面分析（百度 PaddleOCR-VL API 为主，本地 PaddleOCR/RapidOCR/Tesseract 兜底）产出文本框与置信度；
   - 聚类为题块（题号/题干/作答），生成每题 bbox 列表（默认 5% padding + clamp）；
   - 裁剪生成切片并上传 Supabase，写入 `slice_image_url`（或多切片）；
   - **执行方式**：`/grade` 仅 enqueue qindex 任务到 Redis 队列；独立 worker `python -m homework_agent.workers.qindex_worker` 异步消费并写回 `qindex:{session_id}`；
   - 失败回退：bbox/slice 可为空，warnings 写明“定位不确定，改用整页”。

## Verification
在 Demo UI 中：
- Vision 调试 Tab：直接调用 qwen3/doubao，确认能拿到完整识别文本。
- 智能批改 Tab：确认 `/grade` 返回 `vision_raw_text`，判定覆盖每题（学生作答/标准答案/is_correct，选项题 student_choice/correct_choice，verdict 仅 correct/incorrect/uncertain，severity 仅 calculation/concept/format/unknown/medium/minor）。
- 题号检索：在辅导中直接输入“讲讲第27题”，系统能基于 session 索引找到对应题目上下文（无需手工勾选）。
- BBox + Slice：若 bbox 可用，chat 优先使用切片（或 bbox 列表）聚焦；不可用时回退整页，并在 warnings 提示。
- 若启用 BBox + Slice，需要同时启动 qindex worker；否则 qindex 会提示 `qindex queued/queue unavailable` 并回退整页。
