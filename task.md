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
