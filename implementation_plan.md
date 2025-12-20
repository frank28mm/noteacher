# Implementation Plan - Fix Timeouts, Restore Vision Text, and Optimize

## Goal Description
1. **Restore Vision Traceability**: Ensure `vision_raw_text` is in schema and returned by API.
2. **Fix Timeouts (P0)**: Solve Chat/Grade API timeouts by making backend LLM calls non-blocking.
3. **Fix Schema Error**: Add `Severity.MINOR`.
4. **Optimize Performance**: Add client-side image compression.
5. **Socratic Chat Post-Grading Only**: 辅导仅在完成批改后使用，允许“全对”也可对话；取消 5 轮硬限制，仍保持苏格拉底不直接给答案。
6. **BBox + Slice（路线3）**: 采用传统 OCR/版面分析生成“整题区域 bbox（可多 bbox）”与切片 URL，支持 chat 精准聚焦与回看。
7. **产品化数据路径（Submission）**：前端只上传原始文件给后端；后端按 `user_id` 存储原图并返回 `upload_id`（一次上传=一次 Submission），后续 `/grade`/`/chat`/qindex/视觉事实抽取都围绕这份“权威原图”展开。
8. **保留策略与可解释降级**：对话历史 7 天、切片 7 天；原始图片+识别原文+批改结果长期保留（系统静默 180 天清理）；无 Redis/OCR 时写入可解释占位（skipped/queued）。
9. **报告与错题排除**：错题“删除”语义为排除（只影响统计/报告）；报告异步生成，可下载与查看历史报告。

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
7. **后端权威上传（/uploads）**：
   - 新增 `POST /api/v1/uploads`：后端上传到 Supabase Storage（用户隔离路径），返回 `upload_id + page_image_urls`；
   - `POST /api/v1/grade` 支持 `upload_id`：当 `images=[]` 时，后端按 `user_id + upload_id` 反查存储并补齐 images；
   - Dev 阶段用 `X-User-Id` / `DEV_USER_ID` 兜底；上线后替换为真实登录体系（Supabase Auth/JWT）。
8. **URL 抓取不稳定兜底**：
   - 模型侧抓 `image_url` 失败时，后端生成压缩后的 “proxy 轻量副本”上传 Supabase，并将 page_image_urls 指向 proxy（仅失败时触发，不增加常规耗时）；
   - 仍失败则走 data-url(base64) 直喂 Vision（绕开供应商抓 URL）。
9. **视觉事实抽取（稳定优先）**：
   - `/grade` 同一次 Vision 调用生成 `visual_facts`（仅用于审计/复盘）与 `judgment_basis`（用于展示）。
   - Chat 只读 `judgment_basis + vision_raw_text`；若 `visual_facts` 缺失，仍给出结论但需提示“视觉事实缺失，本次判断仅基于识别文本”。
   - 当 grade 阶段出现“视觉风险” warning 时必须切片（qindex must-slice）。
10. **Chat “看图”兜底（只读缓存）**：
   - 若切片未生成或 facts 为空：返回“切片生成中/看不清，稍后再试”，禁止臆测式解释。
10. **数据持久化（下一阶段）**：
   - 将每次 Submission 的“原始图片 + vision_raw_text + 批改结果”落到 Supabase Postgres（支持按时间查询）；
   - chat_history 与切片按 7 天 TTL 清理；系统按 last_active_at 对静默 180 天数据做清理；
   - 引入 `mistake_exclusions`（排除）与 `report_jobs/reports`（异步报告）表结构。

## Verification
在 Demo UI 中：
- Vision 调试 Tab：直接调用 qwen3/doubao，确认能拿到完整识别文本。
- 智能批改 Tab：确认 `/grade` 返回 `vision_raw_text`，判定覆盖每题（学生作答/标准答案/is_correct，选项题 student_choice/correct_choice，verdict 仅 correct/incorrect/uncertain，severity 仅 calculation/concept/format/unknown/medium/minor）。
- 题号检索：在辅导中直接输入“讲讲第27题”，系统能基于 session 索引找到对应题目上下文（无需手工勾选）。
- BBox + Slice：若 bbox 可用，优先使用 figure 切片；chat 不做实时看图，仅展示 `judgment_basis + vision_raw_text`。
- 若启用 BBox + Slice，需要同时启动 qindex worker；否则 qindex 会提示 `qindex queued/queue unavailable` 并回退整页。
- Upload->Grade：用 `POST /uploads` 拿到 `upload_id + page_image_urls`，再用 `/grade(upload_id)` 跑通整条链路（前端无需直传 Supabase）。
