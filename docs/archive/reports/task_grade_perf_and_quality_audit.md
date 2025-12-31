# Task：/grade（Ark Doubao）性能与质量审计 + 改造方案（待办）

> 目的：把当前“/grade 慢且难解释”的问题拆成可测的瓶颈，并形成可落地的改造清单。
> 注意：本 Task 是工程待办，不替代路线图/Backlog；后续落地按小步 PR 推进。

## 背景
- 现状：本地跑 `/api/v1/grade` 体感耗时长；怀疑 Ark 侧通过 URL 拉图耗时。
- 对照：豆包 App/官网作业批改 10–20s 出结果（偏“快”，但存在误判/互斥）。
- 我们的差异化：需要“可信 + 可解释 + 可纠错 + 可运营”，并在此基础上优化体感速度。

## 目标（可验证）
1) 建立可观测的耗时拆分：能回答“慢在上传/下载、预处理、切片、VLM、LLM、解析、存储哪个阶段”。
2) 形成 1 份结论报告：给出 Top3 瓶颈、复现实验与数据。
3) 输出改造 PR 列表（按收益/风险排序），并明确每项验收口径。

## 范围
- 仅覆盖 `/api/v1/grade` 的主链路（含 autonomous preprocess + aggregator）。
- 不做：按班级/年级/教材版本分群；不做“练习量归因”。

## 现有实现点位（阅读入口）
- `/grade` 入口与持久化：`homework_agent/api/grade.py`
- autonomous 主流程（preprocess/plan/reflect/aggregate）：`homework_agent/services/autonomous_agent.py`
- 图片下载/压缩（可能引入二次耗时）：`homework_agent/services/autonomous_tools.py`（`_compress_image_if_needed`）
- Vision 调用（Ark responses API）：`homework_agent/services/vision.py`
- Supabase 上传/URL 产出：`homework_agent/utils/supabase_client.py`

## 任务清单

### T0. 启用 Ark `image_process`（开关化 + 可回退）
- 代码侧先打通“能开”：
  - 新增 env：`ARK_IMAGE_PROCESS_ENABLED=1`
  - 仅在 `/grade` 的 Aggregator 阶段尝试启用（其它路径保持不变）
  - 若 Ark 侧 tools 调用失败，自动回退为不带 tools 的 `responses.create`（best-effort）
- 验收：开关开启时，不影响正常返回；日志中能区分“工具启用/未启用/回退”。（后续在 T1 做耗时拆分时一起落点）
- ✅ 已实现：见 `homework_agent/services/llm.py`、`homework_agent/services/autonomous_agent.py`、`homework_agent/utils/settings.py`、`.env.example`、`.env.template`

### T1. 加入端到端 timing breakdown（日志 + 指标）
- 在以下阶段打点并统一字段：
  - preprocess（qindex_fetch / vision_roi_detect / diagram_slice / ocr_fallback）
  - `_compress_image_if_needed`（download+resize+upload 三段耗时）
  - aggregator LLM 调用（request/response/parse）
  - update_submission_after_grade（DB upsert）
- 输出：每次 grade 生成 `timings_ms`（结构化 dict），并写 `log_event`。
- 验收：1 次 grade 日志中能看到完整耗时拆分；可以按 request_id 聚合。
- 顺手记录并落库：Ark Responses 的 `response_id`（用于后续用官方接口查询/取上下文做审计与复现）。
- ✅ 已实现（response_id）：`/grade` 日志事件 `grade_ark_response_id` + qbank meta + submissions.grade_result._meta（upload_id 存在时）
- ✅ 已实现（prompt 兼容性）：Ark Responses 调用将 system prompt 迁移为顶层 `instructions=...`（避免把 system 当作 input message）
- ✅ 已实现（timings_ms）：`grade_done.timings_ms` 已包含完整拆分（preprocess / compress / tools / llm），已在 A/B 测试中验证。

### T2. 复现实验矩阵（找出“URL 拉图”真实占比）
对同一份作业样本，分别跑：
- A) 直接用 Supabase public URL（现状）
- B) 预先生成压缩 proxy（同 bucket，同区域）
- C) 对高风险题/小目标题使用 Data URL（base64）作为复核（少量）
记录：总耗时、VLM 耗时、失败率（超时/5xx/429）、tokens。
实现方式（便于一键跑 A/B/C）：
- 通过 env `GRADE_IMAGE_INPUT_VARIANT` 或 Header `X-Grade-Image-Input-Variant` 切换：
  - `url`：upload_id 解析时强制用 `page_image_urls`（不走 proxy）
  - `proxy`：upload_id 解析时优先用 `proxy_page_image_urls`（若存在）
  - `data_url_first_page`：Ark 聚合阶段将首张输入转成 data URL
  - `data_url_on_small_figure`：仅当检测到 `figure_slice_too_small` 时启用 data URL（少量复核）
- ✅ 已完成（A/B测试）：2025-12-31 完成三组对比测试，结论见 [`docs/reports/perf_audit_ab_test_results.md`](perf_audit_ab_test_results.md)。推荐 Proxy 策略（收益 >15%）。

### T3. 质量差异化门禁（先做“保守判对”）
- 定义高风险触发条件（示例）：warnings 包含 OCR/指数不清晰/图形题；或 reasoning 自相矛盾；或 evidence 不足。
- 策略：高风险时 `verdict` 不允许直接输出 `correct`，降级为 `uncertain/needs_review`（fail-closed）。
- 验收：在回归样本中，减少“错判为对”的高风险 case；并能解释降级原因。
- ✅ 已实现：新增 `high_risk` 服务模块，并在 `grade.py` 最终生成结果前注入 `enforce_conservative_grading` 逻辑。检测到 `ocr_failed`, `visual_risk` 等警告时自动降级。

### T4. Ark 模型能力利用评估（针对 Doubao-Seed-1.6-vision）
- 现状确认：
  - Ark vision 使用 `responses.create`，现已支持按开关启用 `tools=image_process`（失败自动回退）。
- 评估方向：
  - 对“指数小/模糊、细小目标、旋转/倾斜”的题，试验开启 image_process（zoom/rotate 等）是否能提升准确率/降低 uncertain。
  - 评估是否可用 Doubao grounding 替代/补强现有 qindex/bbox。
- 输出：一页结论（可行/不可行、接口改动点、风险）。
- ✅ 已就绪：环境配置 `ARK_IMAGE_PROCESS_ENABLED` 已生效，代码已支持向 Ark 传递 `tools=[image_process]`。鉴于目前样本为标准件，建议在后续“坏样本”专项中开启此开关进行对比测试。

### T5. 多轮/可审计链路验证（Responses Context）
- 目的：明确 single-turn 与 multi-turn 的差异，并把“可复现/可审计”落到接口层。
- 参考官方接口：
  - 查询模型响应：`GET /api/v3/responses/{response_id}`
  - 获取响应上下文：`GET /api/v3/responses/{response_id}/input_items?...&include[]=message.input_image.image_url`
- 验收：能够从日志中的 `response_id` 拉回该次请求的 input items（含 image_url/base64），用于定位“模型侧拉图/工具调用”的真实行为。

## 交付物
- `docs/reports/grade_perf_and_quality_audit_report.md`（数据 + 结论 + Top3 改造）
- 若进入实施：对应的 PR 列表（每个 PR 只做一件事，带回归样本）。
