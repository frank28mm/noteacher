# Task List (LLM 判定标准 & Demo 对齐)

- [x] Analyze logs and code
- [x] `schemas.py`: Add `vision_raw_text`, `Severity.MINOR/MEDIUM`
- [x] `routes.py`: Return `vision_raw_text` in all GradeResponse paths；chat_stream 用线程池避免阻塞
- [x] `demo_ui.py`: 展示 `vision_raw_text` 预览；新增 Vision 调试 Tab（直调 qwen3/doubao 查看识别原文）
- [x] 删除 `verify_full_workflow.py`（改用 Demo/调试入口）
- [ ] **LLM 判定标准落地**
    - [ ] Prompts: 全题覆盖，必须输出学生作答/标准答案/is_correct；选项题写明 student_choice/correct_choice；verdict 仅 correct/incorrect/uncertain；severity 仅 calculation/concept/format/unknown/medium/minor；不确定标明 uncertain；不编造 bbox；返回 `vision_raw_text`
    - [ ] 文档：更新 `agent_sop.md`、`docs/engineering_guidelines.md` 说明上述标准
- [ ] **验证**
    - [ ] 用 Demo 调试 Tab 直调 Vision（qwen3/doubao）确认能拿到识别原文
    - [ ] 用 Demo 批改 Tab 跑一张样例，确认 Grade 返回 `vision_raw_text` + 判定字段符合新标准
