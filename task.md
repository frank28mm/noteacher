# Task List (LLM 判定标准 & Demo 对齐)

- [x] Analyze logs and code
- [x] `schemas.py`: Add `vision_raw_text`, `Severity.MINOR/MEDIUM`
- [x] `routes.py`: Return `vision_raw_text` in all GradeResponse paths；chat_stream 用线程池避免阻塞
- [x] `demo_ui.py`: 展示 `vision_raw_text` 预览；新增 Vision 调试 Tab（直调 qwen3/doubao 查看识别原文）
- [x] 删除 `verify_full_workflow.py`（改用 Demo/调试入口）
- [ ] **LLM 判定标准落地**
    - [x] Prompts: 全题覆盖，必须输出学生作答/标准答案/is_correct；选项题写明 student_choice/correct_choice；verdict 仅 correct/incorrect/uncertain；severity 仅 calculation/concept/format/unknown/medium/minor；不确定标明 uncertain；不编造 bbox；返回 `vision_raw_text`
    - [x] 文档：更新 `agent_sop.md`、`docs/engineering_guidelines.md`、`README.md`、`API_CONTRACT.md` 对齐上述标准
- [ ] **验证**
    - [x] 用 Demo 调试 Tab 直调 Vision（qwen3/doubao）确认能拿到识别原文
    - [x] 用 Demo 批改 Tab 跑样例，确认 Grade 返回 `vision_raw_text` + 判定字段符合新标准

- [ ] **Phase 2: 题号检索 + BBox/Slice（路线3：OCR/版面分析）**
    - [x] `/grade` 后写入 session 全题快照（qbank，按 question_number 可查）
    - [x] `/chat` 支持用户直接点名“第23题/第19题”，无需手工勾选错题
    - [x] OCR/版面分析生成整题 bbox（可多 bbox），默认 5% padding + clamp（qindex；由独立 worker 生成）
    - [x] 裁剪并上传切片图到 Supabase，写入 `slice_image_url`（失败回退整页 + warnings；由独立 worker 生成）

- [ ] **Phase 3: Submission（权威原图）+ 保留策略 + 报告**
    - [x] 新增 `POST /api/v1/uploads`：后端上传 Supabase（用户隔离路径），返回 `upload_id + page_image_urls`
    - [x] `/grade` 支持 `upload_id`（images 为空时按 user_id 反查并补齐）
    - [x] URL 拉取不稳兜底：失败时生成“轻量 proxy 副本”并重试；仍失败走 data-url(base64) 直喂 Vision
    - [ ] Supabase 表结构：`submissions`/`mistake_exclusions`/`report_jobs`/`reports`（含 RLS 策略草案）
    - [ ] `/grade` 完成后将“原始图片 + vision_raw_text + 批改结果”持久化为 Submission（按时间可查）
    - [ ] Chat 首屏：基于 Submission 拉取并展示“批改结果 + 识别原文 + 原始图片”（对话历史仅 7 天）
    - [ ] 错题删除语义：仅排除（影响报告统计，不改历史事实）
    - [ ] 报告异步生成：支持自定义时间段、下载与历史报告列表；报告保存输入快照便于复现/迭代
    - [ ] 清理策略：chat_history 7 天、切片 7 天、静默 180 天数据清理（定时任务/cron）
    - [ ] Demo UI：改为走 `/uploads -> /grade(upload_id)` 端到端验证（用户确认后再做）
