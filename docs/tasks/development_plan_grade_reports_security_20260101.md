# 开发执行计划（Grade 性能/质量 + Reports/Worker/RLS + 密钥治理）

> 本计划是“当前一轮执行计划/跟踪表”，从 `docs/cto_90_day_plan.md`（路线图）与 `docs/agent/next_development_worklist_and_pseudocode.md`（Backlog）中抽取必要条目，并补齐我们最近讨论的 Ark Responses API、image_process、RLS/权限与 schema 口径对齐的落地细节。
>
> 原则：**不新增第二份路线图/Backlog**；本文件只负责“把要做的事列清楚、可验收、可追踪”。

## 0) 目标与非目标

### 0.1 目标（用户可感知）

- **差异化质量**：对错判定必须可解释（judgment_basis/证据链），证据不足明确标注 `uncertain/needs_review`，拒绝“看起来很快但互相矛盾”的输出。
- **体验可控**：把 `/grade` 的慢拆解成可量化分项（抓图/压缩/定位/LLM 推理/DB 写入），能定位瓶颈并做优化决策。
- **闭环可扩展**：报告链路从 grade/chat 解耦（异步、可重跑、可审计），为“学情分析师 subagent”提供稳定输入。

### 0.2 明确不做（本阶段不做）

- 不做“按班级/年级/教材版本分群对比”。
- 不做“进步/退步归因到练习量”。

## 1) 现状核对（基于代码/DB 真相）

### 1.1 已落地（已完成）

- Ark Responses API：
  - 将 system prompt 从 `system role message` 迁移到顶层 `instructions=...`（降低兼容性风险）。
  - 支持 `ARK_IMAGE_PROCESS_ENABLED` 开关（开启内置 `image_process` 工具；失败自动回退无 tools）。
  - `/grade` 记录并持久化 Ark `response_id`（便于用官方 GET API 查证“拉图/工具/输入”）。
- `/grade` 性能拆解：
  - 在 qbank meta 写入 `timings_ms`（preprocess/tools/compress/LLM/DB 等分项）。
  - 增加 `/grade` 图片输入策略实验：`GRADE_IMAGE_INPUT_VARIANT=auto|url|proxy|data_url_first_page|data_url_on_small_figure`（支持 header 覆盖）。
- A/B/C 结论留档：
  - 已生成并留档：`docs/archive/reports/perf_audit_ab_test_results.md`

### 1.2 口径偏差与修复状态（以代码/DB 为准）

✅ 已修复（完成验收）

- `GET /reports/{report_id}`：DB schema 为 `reports.id`，代码已统一按 `id` 查询（保留路由参数名 `report_id`，避免 breaking change）。
- `report_jobs` 状态：`supabase/schema.sql` 默认 `queued`；`report_worker` 已兼容拉取 `queued|pending` 并更新状态机（`queued→running→done/failed`）。
- `report_jobs` 锁字段：已具备并在 worker 中写入（`locked_at/locked_by/attempt_count/last_error/report_id` 等）。
- `question_attempts/question_steps`：事实表已存在，`facts_worker` 已持续写入（用于报告特征层与过程诊断）。

证据（运行态确认）

- 表/字段存在性（PostgREST 口径，不依赖直连 Postgres）：`python3 scripts/verify_supabase_tables_rest.py`
- report_jobs 锁/状态流转：在 Reports 页点一次“生成报告（最近一次）”，可观察 `queued→running→done`，并落库 `report_id`

🔄 仍需推进（环境型验收）

- WS‑A：快路径“生产同等网络/并发”复测与留证据（口径区分 `queue_wait_ms` vs `worker_elapsed_ms`，对照 `p50/p95` 阈值）。该项依赖你定义“生产等价环境”的网络/并发基准，完成后再把证据写入 `docs/reports/`。

### 1.3 执行状态快照（滚动更新，避免“我总会忘”）

> 说明：这里是“唯一真相源”的进度面板；新增需求/任务必须先落到本文件与 Backlog，再开始动手做。

- ✅ WS‑A 已完成：
  - A‑1 默认策略：`GRADE_IMAGE_INPUT_VARIANT=url`（快路径固定，先保体验）
  - A‑2 持续审计：`bench_grade_variants_async.py` + 多份 `docs/reports/grade_perf_*` 留档
  - A‑7.1 Layer 3 复核卡（后端）：`review_pending → review_ready/review_failed` 异步更新 `job.question_cards`
  - A‑7.2 Layer 1/2（后端能力已具备）：`question_cards` 的占位/判定字段与 `answer_state=blank` 口径已落地（Demo 可选择隐藏）
- 🔄 WS‑A 待补：
  - A‑4 生产同等网络/并发复测留证据（以 `queue_wait_ms/worker_elapsed_ms` 拆分；对照 `p50/p95` 验收阈值）
- ✅ WS‑C 已完成：
  - C‑4 `GET /api/v1/reports/eligibility` 已实现（权威统计口径：基于 `submissions`，不依赖 `/mistakes`）
  - C‑5 `GET /api/v1/submissions` 已实现（Home Recent Activity / History List 数据源）
  - C‑6 `GET /api/v1/submissions/{submission_id}` 已实现（History Detail 方案B：快照详情秒开）
  - C‑2 facts_worker 已实现并已在 `/grade` 流程入队（`question_attempts/question_steps` 回填；report_worker 含缺省回退路径）
- ✅ WS‑B 已完成（可丢数据也要口径一致）：
  - B‑1 Schema 现场对齐：`report_jobs` 锁字段 + `question_attempts/question_steps` 已在当前 Supabase 项目可用（已用 `scripts/verify_supabase_tables_rest.py` 验证）。
  - B‑2 RLS/权限治理：worker 运行环境启用 `SUPABASE_SERVICE_ROLE_KEY` 且 `WORKER_REQUIRE_SERVICE_ROLE=1`，可稳定 UPDATE `report_jobs`（锁/状态流转/落库 report_id）。
- ✅ WS‑C 已完成（运行态确认）：
  - C‑1 report_worker 稳定化：`queued→running→done/failed` 可观测，锁字段写入与 report_id 落库生效。
- 🧭 新增 P0（本次新增）：A‑8 历史错题复习（Chat Rehydrate，见下）

### 1.4 外部“体检报告”口径校对（以代码为准）

> 结论：外部总结可参考，但部分口径会误导协作（尤其是 SSE 客户端实现与“端点数量”）。统一以本仓库代码与契约为准。

- 代码核对报告：`docs/reports/healthcheck_report_code_alignment_20260103.md`
- 需要特别注意的出入点（避免后续误读）：
  - **API 端点数量**不是稳定指标：当前 `/api/v1/*` 为 20 条 unique paths（以 `homework_agent/API_CONTRACT.md` 为准，不写固定数字）。
  - **SSE 客户端实现**：后端支持 `Last-Event-Id`（恢复 session + 最多重放 3 条 assistant），但当前 demo 前端用 `fetch + ReadableStream` 解析 SSE，尚未接入 `Last-Event-Id` 断线续接。
  - **类型口径**：核心字段已对齐，但前端仍存在少量 `any` 作为过渡（不应宣称“完全无 any”）。

## 2) 工作流拆分（Workstreams）

### WS‑A：/grade 性能与质量（Ark 作为主线）

**目标**：把“慢”拆解为确定瓶颈；把“快但不严谨”改成“可审计 + 可控降级”。

#### A‑1 选择默认图片输入策略（基于现有数据）

- 决策：**当前默认固定 `url`**（先把快路径跑稳 + 提升可解释性）；`proxy` 待闭环修复后再做最小验证并考虑切默认。
- 备注：`data_url_*` 仅用于“少量复核/争议 recheck”，不作为默认全量策略。
- 验收：
  - `/grade` P95（同步场景）显著下降或至少瓶颈可解释；
  - `needs_review_rate` 可控且有原因字段；
  - 产生 `response_id` 且可回查。

#### A‑2 “慢到底慢在哪”持续审计（日志驱动）

- 交付物：
  - 固化关键日志事件与字段：`grade_total_duration_ms`、`preprocess_*`、`compress_*`、`llm_*`、`submission_persist_*`。
  - 对比三组：`Ark URL 拉图 vs base64 少量复核 vs 预生成 proxy`。
    - 日常迭代：每个 variant 先跑 **N=5**，输出 `p50 + max + 失败率/needs_review率`（更快、更省钱，用于判断方向）。
    - 决策/验收：再补一轮 **N=5**（不同时间段/清空队列或隔离前缀后），两轮合并视作 **≈N=10**，再看 `p50/p95` 以减少抽样偶然性。
  - 固化可复跑脚本：`scripts/bench_grade_variants_async.py`（输出 `docs/reports/grade_perf_variants_*.md/.json`）。
- 已跑 N=10（IMG_0699）：`docs/reports/grade_perf_variants_qindex_only_n10_img0699_20260101.md`
- 最新快路径基线（URL-only + qindex_only）：`docs/reports/grade_perf_url_n3_fast_finalize_12000_20260102.md`
- 复盘摘要（含关键实现策略）：`docs/reports/grade_perf_fast_path_summary_20260102.md`
- 验收：每次优化前后都有“可对比的量化证据”，不会凭感觉换策略。

#### A‑3 image_process 的收益验证（不做 A/B 也要可复现）

- 交付物：
  - 在相同输入/相同 `GRADE_IMAGE_INPUT_VARIANT` 下，跑 `ARK_IMAGE_PROCESS_ENABLED=0/1` 两组：
    - 日常迭代：每组先跑 **N=5**
    - 决策/验收：两轮 N=5 合并（≈N=10）
  - 输出：速度（总耗时 + 分项）与质量（wrong_items 稳定性/互斥率/uncertain）对比。
- 验收：明确“哪些题型/哪些场景开启有效”，再决定是否扩大范围。

补充：当前快路径默认不启用 `image_process`（避免 deep-vision 在快路径中长时间思考/拉图）；仅当存在明确图形证据（figure slices）时启用。

#### A‑4 本轮新增：快路径预处理降级 + 实验隔离 + 验收阈值（来自第二轮实测结论）

> 说明：以下是基于两轮实测（Demo + bench）与同事复核形成的“立即可落地”优先级建议；证据留档见：
> - `docs/reports/demo_ui2_run_20260101_133600.md`
> - `docs/reports/grade_perf_root_cause_findings_20260101.md`
> - `docs/reports/grade_perf_variants_full_after_fix_20260101.md`
> - `docs/reports/grade_perf_variants_off_variantprop_20260101.md`

- P0（现在就做，直接改善体验）
  - 默认把 grade 快路径设为 `AUTONOMOUS_PREPROCESS_MODE=qindex_only`（仅复用 qindex 缓存切片；未命中则跳过），把 VLM locator/切片移出快路径，仅在“视觉风险/复核”时触发。
  - 若 qindex 缓存长期未命中/worker 未启用，临时回退到 `AUTONOMOUS_PREPROCESS_MODE=off`（避免被预处理拖慢快路径）。
  - “清除测试干扰”落地为隔离策略：优先用新的 `CACHE_PREFIX` / `DEMO_USER_ID` 做实验隔离（优先级高于 `redis-cli FLUSHDB`）。
- P1（让对比结论更可信、让策略更可运营）
  - 统计策略：日常迭代用 **N=5**（看 `p50 + max + 失败率`），需要做默认策略/验收结论时再补一轮 N=5（合并≈N=10 后看 p50/p95）。
  - 让 `proxy` 变体名副其实：当前更偏 “prefer_proxy”，缺少稳定生成 proxy 资产的机制，导致对比口径不纯；需补齐“生成/回写/复用 proxy_page_image_urls”的闭环后再定默认策略。
  - 增加“单次作业报告”：给 `/reports` 增加 `submission_id` 模式（Demo 展示更符合用户预期；周期性报告 `window_days` 继续保留）。
- P2（工程一致性/文档）
  - `homework_agent/utils/settings.py` 中 `REPORT_NARRATIVE_ENABLED` 的注释与默认值不一致（注释写“keep off by default”，但 `default=True`）；需统一口径，避免误读。

- 验收阈值（用于 /grade 体验达标）
  - 在“无排队干扰”（队列为空/隔离前缀）前提下：同一张图 `p50 < 60s`，`p95 < 120s`（以 `grade_total_duration_ms` 为准，且同时记录分项）。

#### A‑5 视觉题验证（几何/函数图像/复杂示意图）

> 目标：在快路径固定后，用真实视觉题样本验证“何时必须切到视觉证据路径”，并把门槛固化为可解释的规则（宁可 `uncertain` 也不误判为 `correct`）。

- 输入：至少 2 张真实样本（优先：几何 1 张、函数坐标系 1 张）。本轮已用 2 张几何样本完成验证（函数图像待补样复核）。
- 统计：同图重复 **N=5**（与快路径验收口径对齐），记录 `p50/p95` + 失败率/`needs_review_rate`。
- 对比：
  - `AUTONOMOUS_PREPROCESS_MODE=qindex_only`（默认快路径；验证是否需要触发“轻量视觉路径”）
  - `AUTONOMOUS_PREPROCESS_MODE=full`（视觉证据链上限基线；不作为默认）
- 产物：
  - 统一汇总：`docs/reports/grade_perf_visual_validation_20260102.md`
  - 明细（N=5）：`docs/reports/grade_perf_visual_img0699_qindex_only_url_n5_20260102.md`、`docs/reports/grade_perf_visual_img0699_full_url_n5_20260102.md`、`docs/reports/grade_perf_visual_img1100_qindex_only_url_n5_20260102.md`、`docs/reports/grade_perf_visual_img1100_full_url_n5_20260102.md`
- 固化结论（触发规则，已落地实现）：
  - 默认快路径仍是 `qindex_only + url`，但当命中 `visual_risk`（OCR 关键字）或存在 slices 时，切换到“带图 + image_process”（宁可不确定也不误判）。
  - `full` 仅用于“离线复核/正确性上限”，避免把 ~70–100s 的预处理成本带入默认快路径。

#### A‑6 多页作业“逐页可用”体验（方案 A：单 job + partial 输出）

> 背景：多页作业若“必须等全量结束才出结果”，用户体感会很差；而豆包 App 虽快但不严谨，我们的差异化是“可解释 + 可控不确定”，因此更需要把等待变成“逐页可用 + 可选进入辅导”。
>
> 原则：**仍然是 1 个 submission / 1 个 grade job**，只是让 job 在 `running` 期间持续暴露“已完成页”的最小摘要；辅导（/chat）只基于已完成页的证据回答。

- 前端体验目标（Demo UI 2.0）
  - 上传 N 张图后立即显示 `1/N..N/N` 页卡（缩略图/页号）。
  - 第 1 页结果就绪后立即渲染“第 1 页摘要”（错题数/待确认数/needs_review），不等待后续页完成。
  - 每页卡片提供 **“进入辅导（本页）”**按钮（用户可选进入，不强制）。
  - 全部页完成后再展示“本次 submission 汇总”（总错题/待确认/常见错误类型/知识点摘要）与“生成学业报告”入口。

- 后端契约与数据来源（最小改动）
  - `/jobs/{job_id}`（Redis job 状态）在 `running` 时允许返回：
    - `total_pages`（int）、`done_pages`（int）
    - `page_summaries`（list，按 `page_index` 递增；每项包含：`page_index(0-based), wrong_count, uncertain_count, needs_review, warnings(optional)`）
      - 可选（Demo 2.0 便捷）：`wrong_item_ids`（用于“一键进入辅导本页”，不要求稳定存在/不进入正式契约）
  - `qbank:{session_id}` / `GET /session/{session_id}/qbank`：
    - `meta.pages_total/pages_done`（用于 UI 与 chat 边界提示）
    - 逐页追加的 `questions`/`wrong_items` 或等价结构（至少保证“已完成页”的证据链可用于 chat）。

- 关键约束（稳定性/成本）
  - chat 与 grade 解耦：用户在 grade 进行中提问，不应阻塞 grade job；但必须在 UI 提示“当前仅基于已完成页回答”。
  - 成本护栏：允许并发（grade worker + chat LLM）但要有并发/速率控制，避免 provider 限流导致失败率上升。
  - 输出体积：`page_summaries` 只放摘要，避免把完整错题/证据塞进 job payload（详细数据仍以 `qbank`/DB 为准）。

- 验收
  - 多页作业：第 1 页结果出现后，UI 在下一次 polling 内展示该页摘要（无需等全量完成）。
  - chat：在只完成 X/N 时提问，回复必须显式标注“当前基于已完成页（1..X）”，且不引用未完成页内容。
  - 全量完成后，最终 grade 结果与现在的“一次性汇总”口径一致（只是更早可见部分结果）。

- 当前实现（已落地）
  - Worker：`homework_agent/workers/grade_worker.py`（逐页执行 + job partial 更新 + qbank/mistakes 增量写入）
  - Demo UI：`homework_agent/demo_ui.py`（逐页进度展示 + 选择页进入辅导）
  - Chat：`homework_agent/api/_chat_stages.py`（支持 `context_item_ids` 绑定 focus 题号；优先按页消歧）
  - Tutor LLM：`homework_agent/services/llm.py`（未完成页强制免责声明：仅基于已完成页回答）

#### A‑7 三层渐进披露（Question Cards：占位→判定→复核）

> 目标：把“等待批改”从黑盒等待变成**秒级可见、逐步变清晰、可中途交互**的过程；支撑前端“占位卡刷出 + 翻转动画 + 追更模式”。

- 设计对齐文档（供前后端分工）：`docs/design_progressive_disclosure_question_cards.md`
- 当前决策（2026‑01‑03 更新）
  - **P0（前端验收阻塞）只验收 Layer 3「复核卡」**：把“少量高风险题”做成异步复核，不阻塞 grade 完成。
  - Layer 1/2（占位/判定卡）后端已具备，但**前端可先隐藏/不强调**（避免把 Demo 交互复杂度拉高）；后续再启用“翻转/追更”动效即可。

##### A‑7.1 Layer 3 复核卡（P0：前端等验收）

- 触发规则（可解释、确定性、可审计）
  - 输入：每题 `verdict` + `warnings` + `needs_review`（或等价提示）+ 视觉风险（`visual_risk`/`visual_risk_reasons` 推断）+ 是否空题（`answer_state`）
  - 输出：`review_needed=true/false` + `review_reasons[]`（用于 UI 文案与审计）
  - 默认策略：只复核“视觉风险 + needs_review/uncertain”的少量题（每页上限，避免成本爆炸）
  - 代码位置：`homework_agent/core/review_cards_policy.py`（`pick_review_candidates(...)`）

- 复核异步化（不阻塞 grade 完成）
  - 目标体验：grade 先 `done`；复核题卡先显示 `review_pending`；复核完成后卡片升级为 `review_ready/review_failed`
  - 关键约定（必须对齐前端）：**即使 `job.status=done`，`job.question_cards[]` 仍可能在短时间内继续被复核 worker 更新**
    - 前端轮询策略：不能在 `done` 立即停止 polling；应在“无 `review_pending` 卡片”或“达到 timeout”后停止
  - 后端实现：`homework_agent/services/review_cards_queue.py`（入队+防重锁）+ `homework_agent/workers/review_cards_worker.py`（消费队列并 patch job 卡片）

- 复核数据来源与调用约束
  - 优先复用：qindex 产出的 bbox/slice；若无切片则临时降级为整页复核（更慢更贵，只用于少量题）
  - 调用：VFE（视觉事实提取）在 fail‑closed 下运行；证据不足必须保持/提升为 `uncertain`，不得“强行判对/判错”
  - 审计：记录复核的 gate/摘要/必要上下文（必要时对齐 Ark response_id）

- `job.question_cards[]` 协议（供前端验收；不破坏 5 字段最小集）
  - 仍保留最小集：`item_id/question_number/page_index/answer_state/question_content?`
  - 新增字段（可选字段，逐步丰富）：
    - `card_state`：`placeholder | verdict_ready | review_pending | review_ready | review_failed`
    - `review_reasons[]`（machine-readable，≤8）
    - `review_summary`（一句话/要点列表，UI 友好）
    - 可选审计字段：`vfe_gate` / `vfe_scene_type` / `vfe_image_source` / `vfe_image_urls` / `visual_facts`

- 验收标准（前端可直接用）
  - 有 `review_needed` 的卡：在 ≤ 1 次轮询内进入 `review_pending`
  - 复核完成后：在 ≤ 1 次轮询内变为 `review_ready/review_failed`，并提供 `review_summary/review_reasons`
  - 非复核题不受影响：仍为 `verdict_ready`；整体耗时不被全量拖慢

##### A‑7.1‑FE 前端验收修复清单（P0，必须做）

> 目的：消除“done 收尾竞态（race condition）”，保证复核卡在 UI 上可验收、可稳定看到最终态。

**状态**：✅ 已完成验收（前端已按口径实现稳健轮询与强制异步；Reports 页的 Hooks 竞态导致白屏问题已修复）

- 轮询停止条件（Robust Polling）
  - 不能只用 `job.status === done/failed` 作为停止条件。
  - 推荐：当且仅当 `(job.status in {done,failed}) AND (question_cards 中不存在 card_state==='review_pending')` 才停止。
  - 安全上限：设置 `max_wait_seconds = GRADE_REVIEW_CARDS_TIMEOUT_SECONDS + 10~20s`，超时则停止并提示“部分复核超时/失败”。
  - 注意：后端不存在 `status=reviewing`；复核进度以 `question_cards[].card_state` 表达。

- `/grade` 同步 done 分支（避免无 job_id 崩溃）
  - 推荐方案：前端对 `/grade` 固定加 header `X-Force-Async: 1`，统一走异步 `job_id` 轮询渲染（最省改动、逻辑最统一）。
  - 备选：前端支持“同步 done 且无 job_id”的结果直出渲染（不走 ResultScreen 轮询）。

- 多图上传真正生效（UI/逻辑一致）
  - `input[multiple]` 已开，但需将 `onUpload` 从 `(file: File)` 升级为 `(files: File[])`，并在 `FormData` 中循环 `append('file', f)`。
  - 后端 `/uploads` 接收 `file: List[UploadFile]`（同名字段重复即可），一次上传=一次 submission。

- Dev 用户注入（仅开发态）
  - 如需使用 `X-User-Id` 兜底（无 Auth），应改为“可配置且仅 dev 启用”（例如 `VITE_DEV_USER_ID`），避免硬编码在前端代码中。

##### A‑7.2 Layer 1/2 占位/判定卡（已具备；前端可暂缓）

- `/jobs/{job_id}` 在 `status=running` 时返回 `question_cards`（轻量列表，支持局部更新，不闪屏）：
  - `item_id`（string，稳定 key）
  - `question_number`（string）
  - `page_index`（int，0-based）
  - `answer_state`（`blank|has_answer|unknown`）
  - `question_content`（可选但强烈建议：题干前 10–20 字）
- 空题口径：用 `answer_state=blank` 表达客观事实；不再使用“无法确认原因”误导用户（不做“不会/遗忘”等动机归因）。
- 时间展示口径：前端展示用后端 `elapsed_ms/page_elapsed_ms`（避免后台 Tab 降频导致 wall time 虚高）。
- 分工（可并行）
  - 后端：生成与增量更新 `question_cards`（占位→判定→复核）、稳定 `item_id`、跨页题号消歧、输出 elapsed 指标
  - 前端：以 `item_id` 为 key 局部更新卡片；占位/翻转动效；空题灰色虚线卡；部分完成即可进入辅导

- 当前实现（已落地 2026‑01‑02）
  - `homework_agent/workers/grade_worker.py`：在 `status=running` 期间写入 `question_cards`（占位→判定），并在 `page_summaries` 增加 `blank_count`
  - `homework_agent/services/grade_queue.py`：初始化 job payload 时补齐 `question_cards`
  - `homework_agent/services/autonomous_tools.py`：新增 `ocr_question_cards`（结构化 OCR，用于占位卡；带缓存）
  - `homework_agent/core/question_cards.py`：稳定 `item_id`/`answer_state` 推断与 merge/sort 工具
  - `homework_agent/demo_ui.py`：监控面板展示 `question_cards` 总量与按页统计（placeholder/verdict_ready/blank）
  - `homework_agent/workers/review_cards_worker.py` + `homework_agent/services/review_cards_queue.py`：
    - 复核卡异步 worker（`review_pending → review_ready/review_failed`），不阻塞 grade 完成
    - 触发规则：`homework_agent/core/review_cards_policy.py`（默认仅复核视觉风险且需要复核的少量题）

##### A‑8 历史错题复习（Chat Rehydrate：不依赖 24h TTL，P0）

> 背景：当前 24h TTL 清理的是 **session/qbank/job/qindex 等短期缓存**（Redis 自动过期），不是 `submissions` 真源快照。  
> 结果：错题本能看历史（来自 `submissions.grade_result.wrong_items`），但**两天后点“问老师”可能因为 session/qbank 过期而无法辅导**，这不符合真实用户体验。

- 目标体验（用户可感知）
  - 用户在任意历史 submission（≥48h）里点某题“问老师”，**无需重新上传**，也能进入辅导。
  - 系统明确说明证据来源：仅基于该 submission 的快照/证据回答；证据不足必须 `uncertain/needs_review`。
- 技术方案（后端为主，前端配合少量参数）
  - 扩展 `POST /api/v1/chat` 支持“复习模式”参数（任选其一，二选一落地即可）：
    - 方案 A（推荐）：在请求体新增 `submission_id`（= upload_id）与 `context_item_ids`（至少 1 个题 id）。
    - 方案 B：新增 `POST /api/v1/chat/review`（语义更清晰，避免影响现有 chat）。
  - Rehydrate 逻辑：当 `session_id` 缺失/过期，或提供了 `submission_id`：
    - 从 `submissions` 读取 `grade_result/questions/wrong_items/judgment_basis`（必要时 `vision_raw_text`）；
    - 生成一个**新的** `session_id` 与最小 qbank（只含 context 题 + 必要的证据字段）写入 Redis（仍 24h TTL）；
    - SSE 返回时在首包事件中携带 `session_id`（前端保存后续继续对话）。
- 分工（用于联调验收）
  - 前端：从“错题详情”发起 chat 时带 `submission_id + item_id`（作为 `context_item_ids=[item_id]`）；拿到首包 `session_id` 后继续同一会话。
  - 后端：保证“历史错题可聊”不依赖旧 session；并在回复中标注证据边界（仅该 submission）。
- 验收标准（可自动化）
  - 构造一个 ≥48h 前的 submission（或手动将 session TTL 设为 60s 复现过期），仍能成功进入辅导并得到与该题证据一致的回答；
  - 不出现“请重新上传/题库快照不存在”这类阻断性提示；
  - 产出可审计字段：`submission_id/item_id/session_id` 三者可串联排查。

### WS‑B：Supabase Schema/RLS/权限（支撑 Worker 稳定运行）

**决策偏好**：因为现阶段数据可丢，可选择“重置到真源 schema + 增量补齐缺失表/字段”。但**禁止**再引入“DROP SCHEMA + 迁移文件强对齐”这套会导致口径漂移的方案。

#### B‑1 Schema 真源与变更方式

- 真源：`supabase/schema.sql`（现网/现库真实口径）。
- 变更方式：
  - 增量 SQL（推荐）：为 `report_jobs` 增加锁字段；创建 `question_attempts/question_steps` 或等价宽表；补齐索引。
  - 或重置（允许）：若决定清库，可在 Supabase SQL Editor 重新执行 `supabase/schema.sql` 后再执行增量 SQL。
- 验收：DB schema 与代码/worker 口径一致（字段/状态值/可写权限），不再需要“适配层”绕来绕去。

参考增量脚本：`supabase/patches/20260101_add_facts_tables_and_report_job_locks.sql`
快速校验工具（推荐先用 REST 校验，再做 DB 直连校验）：
- `python3 scripts/verify_supabase_tables_rest.py`：用 PostgREST 验证关键表/列可读（不需要 DB 密码）
- `python3 scripts/verify_supabase_schema.py`：用 `SUPABASE_DB_URL` 直连 Postgres 校验默认值/RLS/策略（需要 DB 密码）
- `python3 scripts/apply_supabase_sql.py supabase/patches/20260101_add_facts_tables_and_report_job_locks.sql`：直连执行 DDL（需要 DB 密码；仅开发库）

#### B‑2 RLS/权限路线（Phase 1.5）

- 推荐：**worker 使用 service role key**（绕过 RLS），API 仍使用 anon key（开发期）或 auth key（生产）。
- 风险控制（必须执行）：
  - service role key 只存在于 worker 进程运行环境（Secret Manager/部署环境变量），不进入仓库文件。
  - CI 增加“误提交检测”（已落地，见 `scripts/check_no_secrets.py` 与 `.github/workflows/ci.yml`）。
  - 建议（可选）：制定轮换策略（例如每月/每次疑似泄露后立刻轮换）。

**状态**：✅ 已落地（worker 已在运行环境启用 `SUPABASE_SERVICE_ROLE_KEY` 且 `WORKER_REQUIRE_SERVICE_ROLE=1`；report/facts worker 可稳定写库）

### WS‑C：Reports/Facts Worker 端到端闭环

#### C‑1 report_jobs 状态与锁

- **明确决策：选择方案 A（改 DB，加锁字段）**。
  - 理由：`locked_at/locked_by` 是业界标准实践；一次性在 DB 层解决并发抢占与可观测性问题，能让 worker 代码更简洁、更可维护。
  - 备注：方案 B（只改代码）仅作为应急兜底（当 DB 无法变更/权限受限时），否则会把“锁/重试/幂等”的复杂度转移到代码侧。

- DB 侧（方案 A，推荐）：
  - `report_jobs` 增加：`locked_at/locked_by/attempt_count/last_error`。
  - 允许 worker 用原子条件更新（`status in ('queued','pending')` 且 `locked_at is null or expired`）。
- 代码侧：
  - `report_worker` 支持拉取 `queued|pending`，并在锁成功后改为 `running`。
- 验收：多实例 worker 下同一 job 只会被一个 worker 处理；失败可重试且有 attempt 记录。

**状态**：✅ 已完成运行态验收（已在本 Supabase 项目观察到 `queued→running→done`，并落库 `locked_* / report_id`）

#### C‑2 facts_worker 与小批量回填

- 交付物：
  - 支持“最近 N 条 submissions 回填”为事实表（进度日志/速率统计/可中断续跑）。
  - 回填后跑一次“统计对比”（与 submissions.grade_result.questions 的分母/分子口径一致）。
- 验收：
  - `question_attempts/question_steps` 的行数随回填增长，且 `mistake_exclusions` 能正确过滤；
  - 生成报告的 Features Layer 结果稳定可审计。

**状态**：✅ 已完成运行态验收（事实表已持续写入，可用 `python3 scripts/verify_supabase_tables_rest.py` 与表行数统计确认）

#### C‑3 报告 API 与产物

- API：
  - `POST /reports` 创建 job（status 初始与 DB 默认一致：`queued`）。
  - `GET /reports/jobs/{job_id}` 查询状态；`GET /reports/{report_id}` 按 `reports.id` 查询（已修）。
- 验收：创建→worker 消费→写入 `reports`→查询返回闭环跑通。

#### C‑4 Report Eligibility（产品周期门槛 + Demo 快速解锁）

> 背景：前端“Report 解锁”不能通过 `/mistakes` 推断（全对 submission 会被漏掉）。应由后端提供权威统计口径，前端只展示进度条/禁用态。

- 需求口径（与产品对齐）
  - Demo：≥3 次 submission（不看对错）即可解锁“周期性报告”入口（用于联调/演示）
  - 产品：同科目 ≥3 天（或配置天数）且满足最小 submissions/attempts 才解锁（避免“数据不足也生成报告”）
- ✅ 已实现接口（契约已写入 `homework_agent/API_CONTRACT.md`）
  - `GET /api/v1/reports/eligibility?mode=demo|periodic&subject=math&min_distinct_days=3&min_submissions=3`
  - 返回：`eligible/current_submissions/current_distinct_days/required_* /reason`（并提供 demo 友好的样本 submission_ids）
- 数据源（权威）
  - 优先：`submissions`（按 `created_at` + `subject` + `user_id` 聚合）
  - 兜底：`user_uploads`（仅代表上传，不代表 grade 完成；需谨慎）

#### C‑5 Submissions/History List（Stitch UI：Recent Activity / History）

> 背景：Stitch UI 需要“最近批改记录/历史作业列表”。此口径必须来自 `submissions` 真源（不能用 `/mistakes` 推断，否则“全对作业”会消失）。
>
> 前端真源：`docs/frontend_design_spec_v2.md`
>
> 后端缺口执行清单：`implementation_plan_backend_gaps.md`

- 交付物（API）：
  - `GET /api/v1/submissions?subject=math&limit=20&before=2026-01-03T00:00:00Z`
- 返回建议字段（最小可用）：
  - `submission_id/created_at/subject/total_pages/done_pages`
  - `summary`（可选，但建议提供）：`total_items/wrong_count/uncertain_count/blank_count/score_text`
  - `session_id`（可选）：若存在且仍有效，前端可直接进入辅导；否则走 A‑8（Rehydrate）
- 数据源：
  - `submissions` 表（按 `user_id + subject + created_at desc`）
  - `summary` 优先从 `grade_result` 快照计算（允许为空，前端降级展示“已批改/查看详情”）
- 验收：
  - Home Recent Activity 能展示最近 N 次作业（包含全对作业）
  - History 列表点击进入“作业详情”（方案 B：快照详情）：`GET /api/v1/submissions/{submission_id}`，无需重建 job

#### C‑6 Submissions/History Detail（方案 B：快照详情）

- 交付物（API）：
  - `GET /api/v1/submissions/{submission_id}`
- 返回字段（用于前端直接渲染）：
  - `question_cards/page_summaries/page_image_urls/session_id`
- 价值：
  - 访问历史作业“秒开”（不走 LLM/队列）
  - 作为“错题本/历史记录”的权威详情页（并与 A‑8 Rehydrate 组合，保证旧作业可聊）

## 3) 验证与测试方案（必须写进交付）

### 3.1 代码级（CI）

- `pytest -q`：保证单元测试/契约测试全绿。
- `scripts/check_no_secrets.py`：阻止 service role key/JWT 误进仓库（已落地）。

### 3.2 端到端（本地/联调）

- `/grade`：
  - 同一张图重复跑 3 次，记录 `timings_ms` 与 `response_id`；
  - 切换 `GRADE_IMAGE_INPUT_VARIANT` 与 `ARK_IMAGE_PROCESS_ENABLED`，输出对比表。
- `/reports`：
  - 创建 job → worker 抢占 → done/failed → 查询 report。

## 4) 风险清单（Risk Register）

- service role key 泄露：最高风险 → CI 检测 + Secret Manager + 轮换。
- schema 口径漂移：会导致 worker/报告“看似跑了但全是空/错” → 以 `supabase/schema.sql` 为真源 + 增量 SQL。
- RLS 误配置：worker 无法 UPDATE → worker 用 service role 或明确的最小 UPDATE policy（仅开发期）。
- 盲目追求速度：导致“互斥/幻觉/误判” → 强制证据链、uncertain、回查 response_id。

## 5) 与 90 天路线图/Backlog 的对齐结论

### 5.1 对齐点（一致）

- 路线图 Week 1 的 “Schema 对齐（P0）/运行手册/可观测性” 与本计划 WS‑B 完全一致。
- 路线图 Week 2–4 的 “报告链路打底/Worker 拓扑/Redis 必选” 与本计划 WS‑C 一致。
- Backlog 的 WL‑P1‑010（报告 jobs + 学情分析师）与本计划 WS‑C 方向一致。

### 5.2 已回写到 Backlog 的口径修正（✅）

- `report_jobs` 状态：已统一为 `queued` 为默认口径，worker 兼容 `queued|pending`（与 `supabase/schema.sql` 一致）。
- Design Doc 路径：已统一引用 `docs/archive/design/mistakes_reports_learning_analyst_design.md`。
- P0 工程任务：已收敛为 Backlog 条目并持续维护：
  - `WL‑P0‑007：/grade 性能拆解与输入策略对比（url/proxy/data_url + image_process）`
  - `WL‑P0‑008：Worker service role key 治理（CI 防泄露 + 运行手册）`
