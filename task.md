# 开发任务清单（Phase 1 - Agent 核心）
# 说明：MVP 以本地端到端验证为先，先在本机（含本地存储/缓存）跑通，再考虑上线替换。

基准文档：product_requirements.md / agent_sop.md / API_CONTRACT.md / models/schemas.py / implementation_plan.md / docs/vision_providers.md。

- [x] 视觉客户端抽象：`services/vision.py` 根据 provider 选择 silicon/ark，适配 url/base64 输入 → 统一识别结果结构。
- [x] FastAPI 路由骨架（stub）：
  - `/grade` 返回占位，待接入 vision+LLM、幂等/异步逻辑。
  - `/jobs/{job_id}` 查询占位。
  - `/chat` SSE 占位。
- [x] FastAPI 应用骨架：main.py + CORS 中间件。
- [x] 完成 `/chat` SSE 基础框架：limit_reached/last-event-id/context_ids 占位。
- [x] 细化苏格拉底辅导：
  - [x] 上下文注入：`/grade` 缓存错题（带本地 id），`/chat` 按 `context_item_ids` 注入详情，脚本 `verify_context_injection.py` 已验证存储与 LLM 引用。
  - [x] 递进提示策略：Turn 1-5 已在 `llm.py` 初版，脚本 `scripts/verify_socratic_tutor.py` 已验证逻辑有效。
  - [x] last-event-id 续接：支持 session 恢复+重放最近最多 3 条助手消息，续接更平滑。
  - [x] 真实 LLM 调试：验证 Qwen3/Doubao 的 JSON/提示遵循度。
    - [x] 模型切换：Reasoning 模型已强制指定为 `Qwen3-VL-Thinking`，Settings/Timeout 已适配高延迟场景。
    - [x] 苏格拉底流程验证：已跑通 `verify_socratic_tutor.py` (Qwen3-VL, 300s timeout)。
    - [x] 配置优化：`settings.py` 增加 `silicon_reasoning_model` 兜底默认值。
    - [x] 上下文注入验证：已跑通 `verify_context_injection.py`。
    - [x] 评分接口验证：已修复 Prompt，跑通 `verify_grade_llm.py`，JSON 结构校验通过。
    - [x] Vision 接口验证：
      - Doubao (Ark): 已跑通 URL 模式（需公网/白名单 URL），Base64 暂不可用。
      - Qwen3 (Silicon): 已跑通 `verify_vision_qwen.py`，视觉+推理描述精准但响应较慢（Thinking 模型约 40s+）。
    - [ ] 现存限制：`/grade` 真实验证仍卡在图片可达性/格式（本地 URL 不可达、带 data 前缀的 base64 易失败），需用纯 base64 或公网 URL 重试；Redis/持久化/异步未验证。
- [x] **稳定性收尾 (Stability Cleanup)**:
  - [x] Cleanup: Remove `max_retries` from methods (useless param)
- [x] Check: Confirm Redis connection probe in startup
- [x] Verification: Run `verify_stability.py` (Guardrails + Retry + E2E + RateLimit Fail-Fast)
- [x] Strategy: Drop automatic retry for RateLimit (Fail Fast)
- [x] **Phase 2: Gradio Demo UI** (`homework_agent/demo_ui.py`):
  - [x] **UI Scaffold**: Setup Gradio Blocks, Tabs ("作业批改", "苏格拉底辅导"), and CSS styling.
  - [x] **Tab 1: Smart Grading**:
    - [x] UI: Image Upload (File/Clipboard), Subject Select, "Start Grading" Btn.
    - [x] Logic: Call `VisionClient` (OCR/Describe) + `LLMClient` (Grade).
    - [x] Display: Render JSON result as structured Markdown (Score, Wrong Items, Analysis).
    - [x] State: Store `grade_result` for Tab 2 context.
  - [x] **Tab 2: Socratic Tutor**:
    - [x] UI: ChatBot interface.
    - [x] Logic: Inject cached `wrong_items` into system prompt (Context Augmentation).
    - [x] Interaction: Multi-turn conversation with `LLMClient.socratic_tutor`.
  - [x] **Integration**: Run locally (`python -m homework_agent.demo_ui`).
  - [x] **Fixes**:
    - [x] Converted listeners to Sync to avoid async/await runtime errors.
    - [x] Corrected `VisionResult` field access (`.text`).
    - [x] Added English grading support and file size checks.
  - [x] **Reminder**: 当前 RateLimit 采用 fail-fast（不重试）；Redis/异步队列尚未启用，Demo 为本地单进程验证。
- [ ] 异步批处理：`/grade` 大批量仍用 BackgroundTasks + cache_store；需接入 Redis/队列、完善 job 状态更新。
- [ ] 功能验证：数学/英语批改、苏格拉底辅导全链路验收。

## 已完成
- [x] Schema 对齐：`GradeRequest` 增加 `vision_provider`（白名单 qwen3/doubao，默认 qwen3）。
- [x] 配置模板：新增 `.env.template` 与 `.env.example` 对齐的视觉模型配置占位。
- [x] P0 决策与接口契约敲定（需求、SOP、API_CONTRACT、schemas 真源建立）。
- [x] 视觉模型文档 `docs/vision_providers.md`，白名单 qwen3/doubao，默认 qwen3，环境变量示例。

## 备注
- 不使用 Claude Agent SDK；仅 FastAPI + 直接 LLM/Vision API。
- 坐标归一化 `[ymin, xmin, ymax, xmax]` 必填；会话 24h，辅导链只读当前批次。
- 上传策略：URL 优先（禁止 localhost/127/内网，需公网 HTTP/HTTPS），单文件≤20 MB；Doubao 仅 URL，Qwen3 支持 URL（推荐）或 base64 兜底（去掉 data 前缀）。***
