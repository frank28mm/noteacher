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

- WS‑A：生产等价复测已在本地以 worker=2 跑完并留证据（见 `docs/reports/a4_prod_equiv_worker2_summary_20260104.md`）。后续仍需补：
  - ✅ worker=1 vs worker=4 的敏感性对比已完成（用于扩缩容阈值）：`docs/reports/a4_worker_sensitivity_w1_w4_summary_20260105.md`
  - 迁移到生产对象存储（Ark/国内）后的复测（避免 Supabase Storage 并发波动影响结论）

### 1.3 执行状态快照（滚动更新，避免“我总会忘”）

> 说明：这里是“唯一真相源”的进度面板；新增需求/任务必须先落到本文件与 Backlog，再开始动手做。

- ✅ WS‑A 已完成：
  - A‑1 默认策略：`GRADE_IMAGE_INPUT_VARIANT=url`（快路径固定，先保体验）
  - A‑2 持续审计：`bench_grade_variants_async.py` + 多份 `docs/reports/grade_perf_*` 留档
  - A‑4 生产等价（worker=2）复测与留证据（口径拆分 `queue_wait_ms` vs `worker_elapsed_ms`）
    - 证据汇总：`docs/reports/a4_prod_equiv_worker2_summary_20260104.md`
    - 明细（空队列起步）：`docs/reports/a4_w2_burst20_p3_empty.md`
    - 明细（模拟小积压）：`docs/reports/a4_w2_preload4_burst10_p3_backlog.md`
  - A‑4.2 worker 并发敏感性：对比 worker=1 vs worker=4（burst=10、3页/次），用于指导扩缩容阈值
    - 证据汇总：`docs/reports/a4_worker_sensitivity_w1_w4_summary_20260105.md`
  - A‑7.1 Layer 3 复核卡（后端）：`review_pending → review_ready/review_failed` 异步更新 `job.question_cards`
  - A‑7.2 Layer 1/2（后端能力已具备）：`question_cards` 的占位/判定字段与 `answer_state=blank` 口径已落地（Demo 可选择隐藏）
- ✅ WS‑C 已完成：
  - C‑4 `GET /api/v1/reports/eligibility` 已实现（权威统计口径：基于 `submissions`，不依赖 `/mistakes`）
  - C‑5 `GET /api/v1/submissions` 已实现（Home Recent Activity / History List 数据源）
  - C‑6 `GET /api/v1/submissions/{submission_id}` 已实现（History Detail 方案B：快照详情秒开）
  - C‑2 facts_worker 已实现并已在 `/grade` 流程入队（`question_attempts/question_steps` 回填；report_worker 含缺省回退路径）
  - C‑7 报告趋势已实现：`reports.stats.trends`（Top5 知识点 + Top3 错因；自适应 `submission|bucket_3d`）
  - C‑8 Reporter 详情页数据契约补齐：KPI/薄弱点/矩阵之外新增 `coverage`（用于 UI 防误导提示）
  - C‑9 错因体系与 Tooltip 字典补齐：新增 `cause_distribution`（题目级 severity）与 `meta.cause_definitions`
- ✅ WS‑B 已完成（可丢数据也要口径一致）：
  - B‑1 Schema 现场对齐：`report_jobs` 锁字段 + `question_attempts/question_steps` 已在当前 Supabase 项目可用（已用 `scripts/verify_supabase_tables_rest.py` 验证）。
  - B‑2 RLS/权限治理：worker 运行环境启用 `SUPABASE_SERVICE_ROLE_KEY` 且 `WORKER_REQUIRE_SERVICE_ROLE=1`，可稳定 UPDATE `report_jobs`（锁/状态流转/落库 report_id）。
- ✅ WS‑C 已完成（运行态确认）：
  - C‑1 report_worker 稳定化：`queued→running→done/failed` 可观测，锁字段写入与 report_id 落库生效。
- ✅ A‑8 历史错题复习（Chat Rehydrate）已具备并已联调验收：
  - 后端：`POST /api/v1/chat` 支持 `submission_id + context_item_ids`，session 过期可从 submission 快照重建；
  - 前端：已按 `submission_id` 发起辅导，避免“过期就要求重传”。
- ⏳ WS‑D（P2：上线前必须做）：VKE/K8s 部署与按需扩缩容（方案已定，尚未落地 IaC/YAML）
- 🟡 WS‑E（P2：上线前必须做）：定价/配额（BT→CP + 报告券；真源见 `docs/pricing_and_quota_strategy.md`）
  - ✅ 已落地（代码）：`user_wallets/usage_ledger` + BT 扣费（grade/chat/report）+ `GET /api/v1/me/quota`
  - ⏳ 待完成：生产口径验收（扣费/幂等/失败回滚）
  - ✅ 已落地（前端）：余额展示（Home/Mine）+ 402 配额不足 UX（跳转订阅页并提示原因）
    - 备注：当前本地若未走 `/api/v1/auth/sms/verify` 初始化钱包，`GET /api/v1/me/quota` 可能返回 `wallet_not_found`；需补“开发环境钱包初始化”或前端兜底提示
- 🟡 WS‑F（P2：上线前必须做）：用户系统与认证（H5 优先：强制手机号；火山短信；微信/抖音可选）
  - ✅ 已落地（代码）：`/api/v1/auth/sms/send|verify` + JWT（AUTH_MODE=local）+ 注册即 Trial Pack
  - ⏳ 待完成：短信供应商接入（非 mock）+ 生产禁用 `X-User-Id` 兜底验收
  - ⏳ 待完成（前端）：登录态串联（保存/使用 `access_token` → `Authorization: Bearer ...`）；当前仅有 401→/login 的最小跳转
  - ⏳ 待完成（前端）：SSE 断线续接（接入 `Last-Event-Id`；避免断线后重复输出/丢输出）
  - 🟡 F‑5 家庭-子女（Profile）账户切换（真源见 `docs/profile_management_plan.md`）
    - ✅ 已落地（后端）：`child_profiles` + 各业务表 `profile_id` + `/api/v1/me/profiles` + 全链路 `(user_id,profile_id)` 隔离
    - ✅ 已落地（后端）：`POST /api/v1/submissions/{submission_id}/move_profile`（传错账户可补救）
    - ✅ 已落地（前端）：Home 头像快捷切换（2 个头像并排，高亮当前并亮灯；切换时提示）
    - ✅ 已落地（前端）：关键流程强提示 `数据库：{profile}`（Camera/Upload）+ 结果页可补救入口（ResultSummary：move_profile）
    - ✅ 已落地（前端）：Mine「管理子女」CRUD UI（ProfileManagement：添加/重命名/删除；头像为可选项可后置）
- 🟡 WS‑G（P2：上线前必须做）：运营后台（Admin）与客服/审计（最小可用）
  - ✅ 已落地（代码）：`/api/v1/admin/users|wallet_adjust|audit_logs`
  - ✅ 已落地（代码）：`/api/v1/admin/usage_ledger|submissions|reports`（只读查询）
  - 🟡 待联调：配置 `ADMIN_TOKEN`（未配置时会 403，属预期保护）
  - ⏳ 待完成：管理端 UI
- ⏳ WS‑H（P3：上线后第 1 个运营迭代）：支付/订阅自动化（最小版：状态机 + Admin 手工兜底，不绑支付渠道）
  - ⏳ 待完成（前端）：订阅状态展示/取消续费最小入口（Subscribe 页已存在，但未对接 WS‑H 用户侧接口）

### 1.3.1 统一优先级看板（前后端一起看，执行可分开）

> 目的：用一张“跨前后端”的优先级清单对齐推进顺序；**不复制**两边的任务细节，只引用各自真源/清单里的条目 ID。
>
> 前端真源：`docs/frontend_design_spec_v2.md`；前端可执行 Backlog：`docs/agent/next_development_worklist_and_pseudocode.md`（见 `Frontend‑H5 … 执行 Backlog` 小节）。  
> 后端真源：本文件；后端 Backlog：`docs/agent/next_development_worklist_and_pseudocode.md`。

#### Global P0（上线前硬门槛：可运营 + 可控成本）

- 后端：WS‑F / WL‑P2‑003（手机号验证码登录 + JWT；生产禁用 `X-User-Id` 兜底）【代码已落地，待生产验收】
- 后端：WS‑E / WL‑P2‑002（BT 精确扣费 + CP 整数展示；报告券 + reserve；`GET /api/v1/me/quota`）【代码已落地，待联调/验收】
- 后端：WS‑G / WL‑P2‑004（Admin API + 审计日志；先不追求后台 UI）【最小 API 已落地；需配置 ADMIN_TOKEN 并补 UI】
- 前端：补齐“登录态串联（Authorization）+ 钱包初始化/`wallet_not_found` 兜底 + SSE 续接（Last‑Event‑Id）”；余额展示与 402 配额不足 UX 已具备（落地任务写入 `docs/agent/next_development_worklist_and_pseudocode.md` 的 `FE‑P0/FE‑P1/FE‑P2` 条目；页面/文案规则以 `docs/frontend_design_spec_v2.md` 为准）

#### Global P1（付费运营稳定化：减少人工 + 自动结算）

- 后端：WS‑H / WL‑P3‑001（订阅生命周期状态机 + 定时结算；不绑支付渠道；Admin 手工兜底）
- 后端：WS‑A A‑4.2（worker 并发敏感性：按你决策补 worker=1/4 对比，用于扩缩容阈值）
- 后端：WS‑F / WL‑P2‑005（家庭-子女 Profile：数据隔离 + 强提示 + move submission 可补救）
- 前端：FE‑P2‑08（Home 头像快捷切换 + 关键流程强提示 + 可补救入口；对齐 `docs/frontend_design_spec_v2.md` §1.7）
- 前端：订阅状态展示/取消续费最小入口（对齐 WS‑H 的用户侧接口）

#### Global P2（体验升级：Stitch UI 对齐 + 高级感）

- ✅ 前端：Stitch UI 对齐（视觉/动效/卡片 IA；以 `homework_frontend/stitch/` 为参考，不改变后端口径；任务落到 `docs/agent/next_development_worklist_and_pseudocode.md` 的 `FE‑P3`）【按你确认已完成】

### 1.4 外部“体检报告”口径校对（以代码为准）

> 结论：外部总结可参考，但部分口径会误导协作（尤其是 SSE 客户端实现与“端点数量”）。统一以本仓库代码与契约为准。

- 代码核对报告：`docs/reports/healthcheck_report_code_alignment_20260103.md`
- 需要特别注意的出入点（避免后续误读）：
  - **API 端点数量**不是稳定指标：当前 `/api/v1/*` 为 20 条 unique paths（以 `homework_agent/API_CONTRACT.md` 为准，不写固定数字）。
  - **SSE 客户端实现**：后端支持 `Last-Event-Id`（恢复 session + 最多重放 3 条 assistant），但当前 demo 前端用 `fetch + ReadableStream` 解析 SSE，尚未接入 `Last-Event-Id` 断线续接。
  - **SSE 续接状态**：🟡 未完成（当前仅解析 SSE；尚未实现断线自动重连 + `Last-Event-Id` 续接），后续以“能自动恢复 + 不重复输出”为验收。
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

- 工具脚本（A‑4 生产等价复测）
  - `python3 scripts/bench_a4_load_async.py`（uploads→grade→jobs；支持 burst、多页、preload 模拟小积压；输出到 `docs/reports/a4_*.{json,md}`）

- 验收口径（A‑4：更重“稳定 + 先可用”，不再用整份 TTD 硬压）
  - **内部可用性（不含排队）**：job 启动后，第 1 页可用时间 `TTV(page1_after_start)=ttv_first_page_ms-queue_wait_ms`
    - 目标：p50 ≤ 180s、p95 ≤ 240s（你给的体感目标是 2–3 分钟内能开始看/能问）
  - **队列可控（排队）**：记录 `queue_wait_ms` 分布（p50/p95/max），并用到达率×服务时间推导“最低并发 worker”与扩缩容阈值
    - 本轮只跑 worker=2 的基线（你已确认“先测 2，回头再对比 1/4”）
  - **稳定性**：区分“job 仍在跑（timeout）” vs “真实 failed”，并单独统计上传侧 5xx（当前 Supabase Storage 并发下可能波动；生产迁移后再定硬指标）

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

---

### WS‑D（P2：上线前必须做，但不阻塞当前迭代）：VKE/K8s 部署与按需扩缩容（生产化）

> 背景：你已确认优先使用火山生态（Doubao/Ark），因此部署优先选 **火山 VKE（托管 K8s）**。  
> 目标：把系统拆成 `api + 4 workers`，并做到“按需独立扩容 + 不丢任务 + 可观测 + 可控成本/限流”，为全国推广做准备。  
> 方案选择（结论）：采用 **方案一（VKE/K8s + HPA + KEDA）**；不采用“单实例内自扩容”的幻想（单机只能手动/固定进程数，无法按队列自动伸缩），也不优先采用“方案二（Serverless App Engine）”来承载复杂 worker 编排。
>
> ✅ 运营侧参数决策（已确认）：
> - **承载方式**：选择 **方案 B：ECS 常驻 + VCI 承接 burst**（常驻稳态 + 峰值按需弹性）。
> - **grade_worker 单 Pod 并发**：`1`（优先稳态/低失败率，再用“扩 Pod 数”承接峰值）。

#### D‑0 架构拆分（部署视角）

- 5 个 Deployment（或同等工作负载）：
  - `api`：FastAPI/uvicorn（无状态，横向扩容）
  - `grade_worker`：消费 `grade:queue`（最吃资源/最需要弹性扩容）
  - `review_cards_worker`：消费 `review_cards:queue`（小流量，少量常驻即可）
  - `facts_worker`：消费 `facts:queue`（中等流量，少量常驻即可）
  - `report_worker`：查询/锁定 `report_jobs`（小流量，少量常驻即可）
- Redis/DB/对象存储采用托管服务（集群外部依赖），Pod 只做计算与编排。

#### D‑1 健康检查与可恢复性（不丢任务的底线）

- API healthz（Liveness/Readiness）：
  - `/healthz`（liveness）：进程活着即可
  - `/readyz`（readiness）：关键依赖可用（至少 Redis 可用；可选：Supabase 连接可用）
- Worker readiness（建议提供最小“自检”能力）：
  - 检查必需 env（`REDIS_URL`、`ARK_API_KEY`、`SUPABASE_*` 等）
  - Redis ping（必须）
  - 可选：Supabase PostgREST 探活（避免启动后立即因权限/网络失败而反复 crash）
- Worker 优雅退出：
  - 收到 SIGTERM：停止拉新任务，处理完当前任务后退出（避免滚动升级丢任务/重复消费）

#### D‑2 扩缩容策略（先定方案，后续落地为 IaC/YAML）

> 原则：只对“最影响排队”的 `grade_worker` 做强弹性；其他 worker 小副本常驻即可。  
> 扩容目标：优先降低 `queue_wait_ms`，满足“先可用（第一页 2–3 分钟内可问）”。

- `api`：K8s HPA（CPU/内存/并发指标）
  - 建议：`minReplicas=2`，`maxReplicas=20`，CPU target 60%
- `grade_worker`：KEDA（队列深度驱动）
  - 触发源：Redis List `grade:queue`（注意包含 `CACHE_PREFIX` 时需用实际 key）
  - 建议：
    - `minReplicaCount=0..2`（若采用“ECS 常驻”，可设为 1–2 以降低冷启动；若完全依赖 VCI 承接峰值可为 0）
    - `maxReplicaCount=50`（先设保守上限，防止一键打爆上游）
    - `listLength=10`（示例：队列每积压 10 个 job，扩 1 个 Pod；后续用 A‑4.2 数据校准）
    - `cooldownPeriod=300`（避免抖动）
- `review_cards_worker / facts_worker / report_worker`：
  - 建议：常驻 `replicas=1..2`；必要时也可用 KEDA，但上限应很小（例如 max=2..5）

#### D‑3 上游限流/成本护栏（“能扩”不等于“该扩”）

> 你已查到 Ark 模型配额：RPM=30000、TPM=5000000。模型侧通常不是首个瓶颈，但仍必须做护栏，防止扩容把失败率推高。

- `grade_worker` 并发护栏（两层）：
  1) **编排层**：KEDA 的 `maxReplicaCount`（第一层硬上限）
  2) **应用层**：预留开关/参数（未来落地）：
     - `GRADE_WORKER_MAX_INFLIGHT_PER_POD`（每 Pod 并发，默认 1）
     - `ARK_MAX_CONCURRENT_REQUESTS` / `ARK_RPM_SOFT_LIMIT` / `ARK_TPM_SOFT_LIMIT`（软限流，超过则降级/排队/needs_review）
- 对象存储（未来迁移到 Ark/TOS）护栏：
  - 参考（TOS 约束限制）：`https://www.volcengine.com/docs/6349/74823`
  - 关键：监控 429/流控 header（如 `x-tos-qos-delay-time`）并做重试/退避

#### D‑3.1 扩容“开关/参数”（上线前必须冻结口径）

> 目的：扩容不是“越多越好”，而是“可控地把排队压低”。这些参数必须提前定默认值与调整策略，避免线上临时拍脑袋。

- **容量规划口径（已确认，作为预设假设）**
  - 峰值窗口：学期内 18:00–22:00（其余时间平峰≈0）
  - 地域：华东
  - 体验 SLO：`p95(queue_wait_ms) ≤ 30s`（“尽量不排队”）
  - 峰值集中度：18–22 时段内“峰值一分钟”≈均值的 `6×`
  - DAU 假设（付费+刚需，保守高预估）：`100→50% / 1000→40% / 10000→30%`
  - 估算基线（来自 A‑4、3页/份）：`grade_worker job_elapsed_ms` p50≈521s，p95≈681s
  - 并发粗算（只针对 `grade_worker`，pod 并发=1）：`pods_needed ≈ λ_peak(份/分钟) × 11.35(分钟)`（用 p95 服务时间估算，满足严格 queue_wait SLO）

- **API（HPA）**
  - `api.minReplicas / api.maxReplicas`
  - `api.targetCPUUtilizationPercentage`（或并发指标）
- **grade_worker（KEDA）**
  - `grade_worker.minReplicaCount / maxReplicaCount`
  - `pollingInterval / cooldownPeriod`
  - `listLength`（队列阈值：每积压多少 job 触发扩容 1 个 Pod）
  - （可选）`activationListLength`（低水位不扩容，避免抖动）
- **节点层（NodePool Autoscaler / VCI）**
  - `nodepool.min/max`（或 VCI 最大并发上限）
  - 优先把 `grade_worker` 放到“可快速扩容”的节点池（或 Serverless 节点池）
- **应用层并发护栏（与 D‑3 对齐，未来落地到代码/配置）**
  - `GRADE_WORKER_MAX_INFLIGHT_PER_POD`（默认 1）
  - `ARK_MAX_CONCURRENT_REQUESTS`（默认 1～2，结合 A‑4.2 校准）
  - “到达率高 + 上游波动”时的降级开关：复核卡比例下调 / `needs_review` 兜底 / 超时不视为失败

#### D‑4 运营视角的“最低可上线”验收

- 部署验收：
  - `api` 至少 2 副本，滚动升级不中断（或中断 ≤ 30s 可接受）
  - `grade_worker` 可从 0 自动扩到 N，并在队列清空后缩回
  - 任一 worker 崩溃可自动拉起，不丢任务（允许幂等重复消费，但最终结果一致）
- 可观测性验收：
  - 能按 `job_id/request_id/session_id` 串联一次批改（排队/执行/复核/写库）
  - 能区分：模型 429 vs 存储 429 vs 本地超时 vs 网络波动

#### D‑5 代码是否需要修改？（结论：K8s/KEDA 不强依赖，但生产化需要“最小必需”改动）

> 结论口径（给团队统一）：**采用方案一不需要为了“能跑”去改业务逻辑**；但为了“可运维/可扩容/可滚动升级”，需要补齐少量生产化接口与信号处理。

- 不需要改代码也能跑的部分：
  - K8s Deployment/HPA/KEDA 本身不要求改 `/uploads`/`/grade`/`/jobs` 的业务逻辑
  - worker 拆分为 4 个部署也不要求改任务模型（只要环境变量/入口正确）
- 建议补齐的“最小必需”（上线前要做，避免运维踩坑）：
  - API：
    - `/healthz`（liveness）与 `/readyz`（readiness，至少 Redis 可用）
  - Workers：
    - SIGTERM 优雅退出（停止拉新任务，处理完当前任务再退出）
    - 启动时 fail-fast：缺关键 env（如 `REDIS_URL`、`ARK_API_KEY`、`SUPABASE_SERVICE_ROLE_KEY`）直接退出并告警
  - 观测：
    - 统一输出 `request_id/job_id/session_id`，便于排队/执行/复核/写库全链路定位

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

#### D‑6 最小起步配置与成本模板（华东2/上海；方案 B：ECS 常驻 + VCI 承接 burst）

> 目的：回答“最小要买什么、每月固定投入多少、弹性如何计费”，并让团队在 WS‑D 内有可追溯的口径。  
> 说明：价格以火山控制台下单与账单为准；以下为“官网定价/价格计算器”核对到的参考值（便于你先做预算）。

**D‑6.1 资源清单（你问的那些项：作用 + 是否需要）**

- 公网 IP（EIP）：给 NAT/CLB/少量 ECS 提供固定公网 IP；若节点全私网，通常给 NAT 配 EIP。
- NAT 网关：让私网节点出网（拉镜像/访问 Ark/TOS），同时避免节点裸露公网；K8s 生产推荐配。
- 负载均衡（CLB/ALB）：
  - CLB：更偏 L4/基础接入；Demo/早期上线首选（简单、便宜）。
  - ALB：更偏 L7/Ingress（域名/路径路由、灰度/WAF 等）；后期产品化再升级。
- 对象存储 TOS：存放作业原图/压缩图/切片/报告附件；你已决定后续迁移到 Ark/TOS，这块属于必选依赖。
- 文件存储 / 大数据文件存储：共享文件系统或大数据场景；本产品一般不刚需（优先用 TOS + DB）。
- 弹性容器实例 VCI：用于 burst 承接 `grade_worker` 的峰值扩容（按秒计费）；你已选择方案 B。
- 托管 Prometheus：监控与告警（延迟/队列/错误/资源）；早期可先轻量化，正式上线建议启用。
- 镜像仓库：把镜像放火山，避免外网拉取慢/不稳定，并做权限与审计；生产建议必选。
- 日志服务：采集容器日志用于排障/审计；早期可先简化，正式上线建议启用。
- 数据库（RDS 是否要配）：**要配**（或等价托管 DB）。原因：你是付费产品，核心资产是用户/订阅/配额、submissions/mistakes/reports 等长期数据；不建议把这些压在单机盘上赌可靠性。

**D‑6.2 参考价格（已核对的“起步级”口径）**

- VKE 托管集群（专业版）：约 `0.6 元/小时/集群`（≈ `432 元/月`）  
  - 参考：`https://www.volcengine.com/pricing?product=VKE&tab=2`
- ECS 常驻节点（1 台起步）：
  - `ecs.g3i.large (2c8g)`：约 `286.38 元/月/台`
  - `ecs.g3i.xlarge (4c16g)`：约 `539.76 元/月/台`
  - 参考：`https://www.volcengine.com/pricing?product=ECS&tab=2`
- 公网 CLB（BGP、1Mbps、小型I）：约 `77 元/月/个`  
  - 参考：`https://www.volcengine.com/pricing?product=CLB&tab=2`
- EIP（BGP、1Mbps）：约 `23 元/月/个`  
  - 参考：`https://www.volcengine.com/pricing?product=EIP&tab=2`
- NAT 网关（小型、1 个、1 个月）：约 `306 元/月/个`  
  - 参考：`https://www.volcengine.com/pricing?product=NAT_Gateway&tab=2`
- RDS for PostgreSQL（高可用型主备、示例 `rds.pg.d1.1c2g` + 本地SSD 200GiB、1 个月）：约 `360 元/月/套`  
  - 参考：`https://www.volcengine.com/pricing?product=RDS+for+PostgreSQL&tab=2`
- VCI（u1 通用算力型，按秒计费）：
  - vCPU：`0.0000446071 元/秒/核`
  - 内存：`0.0000058748 元/秒/GiB`
  - 参考：`https://www.volcengine.com/docs/6460/111933?lang=zh`
- TOS（华东2示例，按量计费）：
  - 标准存储：`0.099 元/GiB/月`
  - 公网流出：`0.50 元/GB`
  - 参考：`https://www.volcengine.com/pricing?product=TOS&tab=1`

> 备注：火山“托管 Redis”价格计算器入口在当前定价模块中未检索到；请以控制台下单页为准。预算模板见 D‑6.4。

**D‑6.3 最小可部署清单（你已确认：先 1 台常驻，不追求 HA）**

- 必选（固定投入）
  - 1× VKE 托管集群（专业版）
  - 1× ECS 常驻节点（建议先 `4c16g`，最低可用 `2c8g`；你已明确“2 台常驻暂不需要”）
  - 1× 公网 CLB（对外暴露 API）
  - 1× NAT 网关（节点私网出网；通常搭配 1×EIP）
  - 1× RDS for PostgreSQL（建议高可用型，先兜住数据资产）
  - 1× TOS bucket（存放图片/切片/附件）
- 弹性（按需）
  - VCI：承接 `grade_worker` burst 扩容（KEDA 触发扩缩容）

**D‑6.4 成本计算模板（固定 + 弹性）**

- 固定（月费）：
  - `cost_fixed_month ≈ VKE_month + ECS_month + CLB_month + NAT_month + EIP_month + RDS_month`
  - 示例（仅作量级感知，不含 TOS/日志/监控/镜像仓库）：
    - 2c8g 常驻：`432 + 286 + 77 + 306 + 23 + 360 ≈ 1484 元/月`
    - 4c16g 常驻：`432 + 540 + 77 + 306 + 23 + 360 ≈ 1738 元/月`
- 弹性（burst，按秒/按量）：
  - VCI：`cost_vci = Σ(pod_seconds × (vCPU×0.0000446071 + GiB×0.0000058748))`
  - TOS 存储：`storage_gib × 0.099 元/GiB/月`（标准存储示例）
  - TOS 公网出流：`egress_gb × 0.50 元/GB`
  - Redis（托管）：`cost_redis ≈ instance_spec(月费) + backup/persistence + bandwidth/traffic`（以控制台为准）

**D‑6.5 风险说明（1 台常驻的代价）**

- 单节点 = 单点：节点挂掉时 API/常驻 worker 可能全部不可用；但 DB（RDS 高可用）可最大化保护数据资产。
- 后续升级路径（不返工）：
  - 把常驻节点池从 1 台扩到 2 台（HA 起步），并把 `api` HPA `minReplicas` 固定 ≥2。
  - `grade_worker` 逐步更多地由 VCI 承接 burst（更贴合“平峰≈0、晚高峰集中”的业务形态）。

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

### WS‑E（P2：上线前必须做，但不阻塞当前迭代）：定价/配额（BT→CP + 报告券）

> 背景：该产品是付费产品，成本核心来自 LLM tokens；必须在上线前把“配额/扣费/报告券”做成严格、可审计、可控成本的机制。  
> 真源：`docs/pricing_and_quota_strategy.md`

#### E‑0 已确认的口径（必须冻结）

- **BT（后端真实账本）**：`BT = prompt_tokens + 10 * completion_tokens`
- **CP（前端展示单位）**：`1 CP = 12400 BT`
  - 前端只显示：`CP_left = floor(bt_spendable / 12400)`（只显示剩余整数，不显示扣点/小数/百分比）
- **计费覆盖范围**：`grade/chat/report` 全部扣 BT
- **Trial Pack（注册即送，所有注册用户包含付费用户）**：
  - `200 CP` 试用算力 + `1` 张周期报告券 + 对应 `bt_report_reserve`
  - 有效期：**5 天**
- **订阅等级**：S1–S5（月度 CP + 月度报告券 + 数据保留），详见真源文档

#### E‑1 最小落地任务（Backlog 将拆分为可执行条目）

- usage 口径统一：所有 LLM 调用必须落 `prompt_tokens/completion_tokens/total_tokens`（包含 `generate_report` 路径）
- 账户/权益存储：`bt_trial/bt_subscription/report_coupons/bt_report_reserve/trial_expires_at/data_retention_tier`
- 扣费与幂等：
  - 以 `X-Idempotency-Key` 保护（避免重试重复扣费）
  - 失败不扣（或按“可回滚”口径扣），需写清楚状态机
- 对外查询：
  - `GET /api/v1/me/quota` → `{ cp_left, report_coupons_left, trial_expires_at? }`

### WS‑F（P2：上线前必须做，但可分步落地）：用户系统与认证（H5 优先：强制手机号；火山短信；微信/抖音可选）

> 背景：我们从“单次 agent demo”演进为“可持续运营的后端 + workers”。用户/订阅/配额/数据留存必须以 `user_id` 为真源，否则无法做付费产品与运营闭环。  
> 结论：**用户系统不需要单独部署一套服务器**；作为 FastAPI 的 `auth/users/billing` 模块与现有 `/uploads /grade /chat /reports` 同库同鉴权即可（部署仍是 `api + workers` 的 5 组件拆分）。
>
> ✅ 已确认的产品决策（冻结）：
> - 首发形态：**H5（手机浏览器）优先**（渠道偏小红书，链接打开为主；微信内打开会存在但非首要依赖）。
> - 登录方式：**强制手机号验证码登录**（注册=手机号；不提供游客模式）。
> - 短信供应商：优先 **火山短信**（同一云生态，便于账单与权限治理）。
> - 可选后续：微信登录（H5 OAuth）/抖音登录（H5 OAuth），按获客渠道再决定是否上线。

#### F‑0 范围与非范围

- 本阶段包含：
  - 手机号验证码登录（发送/校验/签发 token）
  - `user_id` 真源化：所有业务读写按 `user_id` 隔离
  - 与 WS‑E 对齐：注册即发放 Trial Pack（BT/CP + 报告券 + 预留）
- 本阶段不包含（后续迭代再做）：
  - 完整支付体系与自动续费（可先人工开通/测试）
  - 微信/抖音 OAuth（除非你明确“首发渠道必须微信/抖音内闭环”）

#### F‑1 后端接口草案（契约先行，避免前后端漂移）

- 认证：
  - `POST /api/v1/auth/sms/send`：输入 `phone`；发送验证码（强频控/风控）
  - `POST /api/v1/auth/sms/verify`：输入 `phone + code`；校验后返回 `access_token`（JWT）+ `user` 概要
  - `POST /api/v1/auth/logout`：注销当前 token（可选：加入黑名单/旋转 refresh token）
- 用户：
  - `GET /api/v1/me`：返回 user profile（最小字段：`user_id/phone/created_at/plan_tier`）
  - `GET /api/v1/me/quota`：沿用 WS‑E（CP/报告券剩余量）
- 鉴权约定：
  - 生产：`Authorization: Bearer <token>` 为唯一来源，不再依赖 `X-User-Id`。
  - 开发：允许 `X-User-Id` 作为 DEV 兜底，但必须受 `APP_ENV=dev` 或显式开关控制，避免误上生产。

#### F‑2 数据模型草案（最小可用，便于后续扩展）

- `users`
  - `id`（uuid/ulid），`phone_e164`（唯一），`phone_verified_at`，`created_at`
  - 可选：`last_login_at`，`status`（active/banned）
- `auth_sessions`（或 `refresh_tokens`，若采用长会话）
  - `id`，`user_id`，`created_at`，`expires_at`，`revoked_at`，`device_info`（可选）
- `sms_codes`（推荐放 Redis，DB 仅作审计或失败追踪）
  - `phone`，`code_hash`，`expires_at`，`attempt_count`
- 与 WS‑E 联动字段（可放单表或独立表）：
  - `trial_expires_at`，`bt_trial`，`bt_subscription`，`report_coupons`，`bt_report_reserve`
  - 订阅字段：`plan_tier`，`data_retention_tier`

#### F‑3 安全与风控（短信登录的硬约束）

- 频控（至少三层）：
  1) `phone` 级：60s 冷却；日上限（例如 10 次）
  2) `ip` 级：滑动窗口限流（防撞库/恶意刷短信）
  3) `device_id`（前端生成/持久化）：减少“换号刷”
- 校验：
  - 验证码只存 hash（或仅存 Redis），5–10 分钟过期
  - 错误次数上限后锁定一段时间
- 审计：
  - 记录 `request_id/user_id/phone/ip/user_agent`（脱敏存储），便于追溯

#### F‑4 验收标准（上线前必须满足）

- H5 首发：手机号验证码可完成登录，拿到 `access_token` 后能正常调用 `/uploads /grade /chat /mistakes /reports`（按 `user_id` 隔离）。
- 注册即发放 Trial Pack（与 WS‑E 对齐）：`200 CP + 1 报告券 + bt_report_reserve`，有效期 5 天，且报告券不会被 grade/chat 消耗掉。
- 生产环境禁用 DEV 兜底：`APP_ENV=prod` 时拒绝 `X-User-Id`，强制 `Authorization`。

#### F‑5 家庭-子女（Profile）账户切换（数据隔离 + 强提示 + 可补救）

> 真源：`docs/profile_management_plan.md`（含分期、DB 变更、worker 链路、前端强提示与可补救口径）。  
> 契约：`homework_agent/API_CONTRACT.md`（Profiles Draft），前端真源：`docs/frontend_design_spec_v2.md`（§1.7）。

**目标（v1）**
- 一个家长 `user_id` 下支持多个子女档案 `profile_id`（至少 2 个）。
- **家庭共用配额**：钱包/配额归属 `user_id`，不按孩子独立计费。
- 数据隔离：History/DATA/Reports 等读取/写入均按 `(user_id, profile_id)` 隔离。
- 体验策略：不做上传前阻断式选择；只做“强提示 + 可补救”。

**最小后端落地清单**
- DB：
  - 新增 `child_profiles`
  - 事实表加 `profile_id` 并回填历史数据到默认 profile
- 兼容层：
  - `require_profile_id`：无 `X-Profile-Id` 时自动使用默认 profile（避免阻断旧客户端）
- API（最小）：
  - `GET /api/v1/me/profiles`（供前端拉取与渲染头像切换）
  - `POST /api/v1/submissions/{submission_id}/move_profile`（传错账户可补救）
- Worker：
  - `profile_id` 从 `submissions.profile_id` 贯穿 upload/grade/qindex/facts/report 的写入与查询过滤

**最小前端落地清单**
- Home 右上角头像切换：profiles=2 时两个头像按钮并排，当前高亮（醒目、一眼可见）。
- 请求头注入 `X-Profile-Id`（有 active_profile_id 时）。
- 关键流程强提示：`提交到：<孩子名>`（拍照/上传/开始批改附近），以及结果/历史详情的 `归属：<孩子名>`。
- 可补救入口：在作业详情/汇总页提供“移动到其他孩子”入口（调用 move submission）。

### WS‑G（P2：上线前必须做，但可后置到“首批运营前”）：运营后台（Admin）与客服/审计

> 背景：你提到“用户注册/用户管理/后台管理页面”。这些不需要单独部署一套“用户系统服务器”，但需要在后端提供 **admin 级能力**（只给运营/客服/你自己用），并保证安全可控。  
> 说明：后台页面本质是另一个前端（Admin Web），但它调用的仍是同一套 FastAPI，只是走 `admin` 权限与专用接口。

#### G‑0 目标（运营角度）

- 能查人：按手机号/用户ID定位用户，查看当前订阅、CP/BT 余额、报告券、试用到期等。
- 能查单：按 `submission_id/job_id/report_id` 回放一次作业批改/报告生成的状态与关键日志索引（排障必备）。
- 能控成本：能看到每天/每用户的 BT 消耗、模型调用次数、失败率；并能对异常用户限流/封禁。
- 能做客服：对“误判/复核失败/报告异常”有最小介入能力（标记、重跑、说明）。

#### G‑1 权限模型（强约束，避免后台变成安全洞）

- `admin` 访问必须与普通用户隔离：
  - JWT claim 中包含 `role=admin`（或单独的 admin token），禁止用普通用户 token 访问 admin API。
  - 强制 IP allowlist（至少首发阶段），并记录审计日志（谁在什么时候做了什么）。
- `worker` 与 `admin` 分离：
  - `worker` 用 service role key 写库；`admin` 走 API + admin JWT（避免“把 service role 暴露给后台”）。

#### G‑2 后端接口草案（最小可用，先用 Swagger/脚本也能跑）

- 用户管理：
  - `GET /api/v1/admin/users?phone=...&limit=...`
  - `GET /api/v1/admin/users/{user_id}`
  - `PATCH /api/v1/admin/users/{user_id}`（封禁/解封、备注）
- 权益/订阅（人工客服兜底，后续再接支付自动化）：
  - `POST /api/v1/admin/users/{user_id}/grant`（发放 CP/BT、报告券、延长试用/订阅；必须幂等 + 审计）
  - `GET /api/v1/admin/users/{user_id}/ledger`（BT/券变动流水，只读）
- 作业/报告排障：
  - `GET /api/v1/admin/submissions?user_id=...&limit=...`
  - `GET /api/v1/admin/submissions/{submission_id}`
  - `GET /api/v1/admin/jobs/{job_id}`
  - `GET /api/v1/admin/reports/{report_id}`
- 成本/用量总览（最小报表）：
  - `GET /api/v1/admin/usage/daily?since=...`（按天聚合：BT、请求数、失败率）
  - `GET /api/v1/admin/usage/top_users?since=...`（TopN 成本/失败）

#### G‑3 审计（必须有，否则运营不可控）

- `admin_audit_logs`（或等价表）：
  - `id, actor_admin_id, action, target_type, target_id, payload_json, created_at, request_id, ip, user_agent`
- 验收：每一次 `admin` 写操作都能在审计日志中追溯（可用于纠纷与风控）。

#### G‑4 Admin Web（前端范围说明）

- 首发不要求把“后台页面”做得很漂亮；优先把链路跑通：
  - 一个登录页（仅 admin）
  - 用户搜索/详情页（手机号→用户→权益/历史/用量）
  - 作业/报告回放页（submission/job/report）
- 位置建议：独立一个 admin 前端仓库或同仓库单独目录；与 H5 用户端完全隔离。

### WS‑H（P3：上线后第 1 个运营迭代）：支付与订阅自动化（最小版，不绑支付渠道）

> 背景：你已确定“付费 + 数据留存 + BT/CP + 报告券”是产品核心，但首发不一定要立刻接入完整支付渠道。  
> 目标：先把**订阅生命周期状态机**做成可审计、可回滚、可运营的“内核”，并保证即使支付渠道未接入/异常，也能用 Admin 手工兜底（不影响服务稳定）。

#### H‑0 设计原则（冻结）

- **不绑定支付渠道**：先抽象 `payment_provider`/`provider_ref` 字段占位（微信/支付宝/抖音支付等后续再选），业务逻辑不依赖具体 SDK。
- **幂等 + 可审计**：所有“开通/续费/到期/退款/补发”都必须写入事件流水，且支持 `X-Idempotency-Key`。
- **订阅只改变“权益与期限”**：不直接改历史事实（submissions/mistakes/reports），只改变用户“可用额度/数据保留/优先级”。

#### H‑1 最小订阅状态机（可先满足上线后运营）

- 状态（建议最小 5 个）：
  - `trial_active`（Trial Pack 有效期内）
  - `active`（订阅有效）
  - `grace`（到期宽限期，可配置 0–3 天；避免支付抖动导致立刻降级）
  - `expired`（订阅到期，回退到“仅剩 Trial/余额”）
  - `canceled`（用户主动取消续费；本期仍有效到 `current_period_end`）
- 关键字段（最小）：
  - `plan_tier`（S1–S5）、`data_retention_tier`
  - `current_period_start/current_period_end`
  - `cancel_at_period_end`（bool）
  - `payment_provider/provider_subscription_id`（可空，占位）

#### H‑2 权益发放与扣费边界（与 WS‑E 对齐）

- 每月权益发放（在 period start 触发）：
  - `bt_subscription += plan_monthly_bt`
  - `report_coupons += plan_monthly_report_coupons`
  - `data_retention_tier = plan_data_retention_tier`
- Trial Pack 与订阅叠加：订阅开通不回收 Trial；扣费顺序仍按 WS‑E（先 trial，再 subscription；报告优先用券 + reserve）。

#### H‑3 自动化最小落地方式（不新增常驻服务）

- 采用 **K8s CronJob**（或同类定时任务）运行“日常结算脚本”，避免再加一个常驻 worker：
  - `expire_subscriptions`：每日扫描 `current_period_end`，更新 `active→grace→expired`
  - `grant_monthly_entitlements`：到期续费成功时（或在新 period 开始时）发放月度权益
- 关键：所有结算动作必须可重跑且幂等（事件流水 + 以 period 为幂等键）。

#### H‑4 对外接口（最小可用）

- 用户侧（H5）：
  - `GET /api/v1/me/subscription`：返回 `status/plan_tier/current_period_end/cancel_at_period_end`
  - `POST /api/v1/me/subscription/cancel`：设置 `cancel_at_period_end=1`（不立即降级）
- Admin 侧（复用 WS‑G 权限/审计）：
  - `POST /api/v1/admin/subscriptions/activate`：人工开通（指定 plan_tier + period_end）
  - `POST /api/v1/admin/subscriptions/extend`：延期（售后）
  - `POST /api/v1/admin/subscriptions/revoke`：强制撤销（风控/退款）

#### H‑5 验收标准（上线后 1 个迭代内完成）

- 能在不接支付渠道的前提下完成：开通→续费（人工/脚本）→到期→宽限→过期回退，全链路可观测、可审计、可回滚。
- 任何一次订阅变更都能追溯到：`request_id/user_id/action/before/after/actor`（WS‑G 审计覆盖）。
- 不会因为订阅状态机/结算脚本异常，导致扣费口径漂移或阻断 grade/chat/report。

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

#### C‑7 报告趋势（Report Trends）：知识点 Top5 + 错因 Top3（UI 需求回写，后端负责产出可视化序列）

> 背景：Reporter 详情页需要“趋势图”来展示本周期内的变化，而不是只展示整体统计。  
> 要求：**趋势只覆盖本周期内**（3/7/30 天等预设周期），且必须避免 30 天时点数爆炸。  
> 决策：采用“**自适应粒度**”——点数少时按 submission 真值，点数多时按 **3 天分桶求和**。

**目标 UI（后端输出必须能直接支撑）**：
- 左图：知识点趋势（Top5 薄弱知识点），**5 条曲线**，表示每次作业（或每个 3 天桶）中该知识点的“错题绝对数量”变化。
- 右图：错因趋势（Top3 错因），**3 条曲线**，表示每次作业（或每个 3 天桶）中该错因的“题目绝对数量”变化。
- 图例交互：前端点击知识点/错因名称可弹出说明；后端提供稳定的 `tag/cause` key，说明文案可由前端维护（后端可选在 report stats 中附带 meta 字典）。

**口径（必须写清，避免后续 UI/数据对不上）**：
- 周期：由 `POST /api/v1/reports` 的 `window_days` 决定（周期报告），或 `submission_id`（单次报告）。
- 数据源：以 `question_attempts` 为权威（若 facts 表为空，report_worker 已有从 `submissions.grade_result` 回退提取的兜底路径）。
- 排除语义：趋势与总体统计一致，必须先应用 `mistake_exclusions` 过滤（report_worker 已过滤 attempts）。
- “错题绝对数量”的定义：`verdict in {'incorrect','uncertain'}` 的题目计入（避免把“uncertain”漏掉导致趋势误判）。
- “错因”的口径：优先用 **题目级** `attempts.severity`（`calculation/concept/format/unknown`），避免 steps 稀疏导致曲线不稳定；步骤级 diagnosis 作为后续增强（不阻塞本阶段 UI）。

**自适应粒度（防爆规则，已确定为 3 天）**：
- 计算 `distinct_submission_count`（本周期内、同 subject、过滤后的 attempts 覆盖到的 submission 去重数）。
- 若 `distinct_submission_count <= 15`：输出粒度 `submission`（每次作业一个点）。
- 若 `distinct_submission_count > 15`：输出粒度 `bucket_3d`（按 UTC 日期对 submission 分桶，每 3 天一个 bucket；bucket 内**求和**输出一个点）。

**后端产物（写入 reports.stats/features 层，供前端直接渲染）**：
- 在 `reports.stats`（features json）中新增 `trends` 字段（schema 稳定，允许增量扩展）：
  - `trends.granularity`: `"submission" | "bucket_3d"`
  - `trends.points[]`：按时间升序
    - 通用字段：
      - `point_key`：`submission_id` 或 `YYYY-MM-DD~YYYY-MM-DD`（bucket）
      - `since` / `until`（ISO 或 date string）
      - `total_attempts` / `wrong_attempts` / `uncertain_attempts`（可选但建议，便于解释）
    - `knowledge_top5`：`{ tag -> wrong_count }`（只输出 Top5 tag）
    - `cause_top3`：`{ cause -> wrong_count }`（只输出 Top3 cause/severity）
  - `trends.selected_knowledge_tags[]`：Top5 tag 列表（用于图例）
  - `trends.selected_causes[]`：Top3 cause 列表（用于图例）
  - （可选）`trends.meta`：`{ tag_definitions, cause_definitions }`（若前端不想维护字典，可由后端附带）

**验收标准（前端可直接验收）**：
- 周期=3/7 天且 submissions ≤ 15：趋势点数=作业次数；图例=Top5/Top3；每条曲线能对齐到对应点（不缺点、不乱序）。
- 周期=30 天且 submissions > 15：趋势点数≈ `ceil(days/3)`，且 `granularity='bucket_3d'`；曲线平滑且可解释（bucket 求和）。
- 与总体统计一致：`sum(points[*].knowledge_top5[tag])` 与 features 总体（同 tag 的 wrong+uncertain）在口径上可追溯（允许 Top5 之外的 tag 不计入该 sum）。
- 单次报告（`submission_id` 模式）：允许趋势为空或仅 1 点（`granularity='submission'`），不影响报告生成。

#### C‑8 Reporter 详情页数据契约（KPI/薄弱点/错因/矩阵/评语：保证“可画、可解释、可审计”）

> 背景：Reporter 详情页不仅要趋势图，还要把“薄弱知识点、错因比例、题型×难度、总体表现、AI 建议”完整呈现。  
> 目标：后端保证 `reports.stats`（Features Layer）能直接驱动 UI，避免前端自行“数数/推断口径”。

**必须覆盖的 UI 模块（字段来自 reports.stats / reports.content）**：
- 顶部 KPI（圆形大数字/总览）：
  - 数据源：`stats.overall`
  - 字段：`sample_size/correct/incorrect/uncertain/accuracy/error_rate`
  - UI 约束：必须同时展示 `sample_size`（样本量），避免仅展示百分比导致误解。
- 薄弱知识点 TopN（建议 Top3/Top5 可配置）：
  - 数据源：`stats.knowledge_mastery.rows[]`
  - 字段：`tag/sample_size/correct/incorrect/uncertain/accuracy/error_rate`
  - 口径：按 `error_rate` 降序（或按 `incorrect+uncertain` 降序）排序；必须附带 `sample_size`。
- 错因比例（柱状/饼图）：
  - 数据源（阶段 1）：题目级错因 `attempts.severity` 的聚合（只统计错/待定题；建议新增到 stats；见 C‑9）
  - 现状可用兜底（阶段 0）：`stats.process_diagnosis.severity_counts`（注意：这是 step 级口径，覆盖面可能稀疏）
  - UI 文案提示：必须可点开 “!” 查看口径说明（见 C‑9 meta 字典）
- 题型 × 难度矩阵（薄弱点）：
  - 数据源：`stats.type_difficulty.rows[]`
  - 字段：`question_type/difficulty/sample_size/correct/incorrect/uncertain/accuracy`
- AI 评语（温暖、简洁、基于事实）：
  - 数据源：`reports.content`（Markdown，来自 Narrative Layer）
  - 约束：LLM 只能引用 `reports.stats` 中已计算的数（不可自行“编造趋势/统计”）。

**建议新增的“可解释性指标”（写入 stats，帮助 UI 做防误导提示）**：
- `stats.coverage`：
  - `tag_coverage_rate`：attempts 中有 `knowledge_tags_norm|knowledge_tags` 的占比
  - `severity_coverage_rate`：attempts 中有 `severity` 的占比
  - `steps_coverage_rate`：本周期 steps_sample_size / attempts_sample_size（用于解释“错因图为什么为空/稀疏”）
- UI 用法：当 coverage 过低时展示提示（例如“本期部分题目未能稳定识别知识点标签，薄弱点仅供参考”）。

**验收标准**：
- 同一份报告，前端不做任何“二次计数/推断”，仅依赖 `reports.stats` 就能渲染：KPI、薄弱点 TopN、错因比例、题型×难度矩阵、AI 评语。
- 数据口径自洽：`overall.sample_size == Σ(type_difficulty.rows[].sample_size)`（允许 unknown 合并，但总分母可追溯）。

#### C‑9 错因体系与 Tooltip 说明（Severity/Diagnosis Taxonomy + 可版本化）

> 背景：UI 需要“错因比例 + 右上角 ! 的判断标准说明”。目前 diagnosis_codes v0 过于保守，且缺少中文解释字典。  
> 决策：先做 **题目级 severity** 的稳定口径与说明字典；diagnosis_codes 作为阶段 2 增强。

**阶段 1（P1，优先落地：稳定、覆盖面高）**：
- 在 Features Layer 中新增 `cause_distribution`（题目级）：
  - 数据源：`question_attempts.severity`（由 facts_extractor 提取/派生）
  - 输出建议：
    - `stats.cause_distribution.sample_size`（分母：`incorrect + uncertain`）
    - `stats.cause_distribution.severity_counts`（计数）
    - `stats.cause_distribution.severity_rates`（占比，可选）
- 在报告 stats 中附带 tooltip meta（或提供独立 metadata 接口，二选一）：
  - `stats.meta.cause_definitions`：
    - key：`calculation/concept/format/unknown`
    - value：`{ display_name_cn, standard, examples? }`
  - 版本字段：`stats.meta.classifier_version`（便于后续升级不破坏历史口径）

**阶段 2（P2，增强：更细的“过程诊断/计算习惯差”等）**：
- 扩展 `question_steps.diagnosis_codes`（从 v0 → v1）：
  - 目标：从“只有 calculation_error”扩展到可用于运营解释的 codes（仍需保守/可审计）。
  - 说明字典：`stats.meta.diagnosis_definitions`（code → 中文名/标准/例子）。
  - 注意：steps 覆盖面天然小（仅有步骤结构的题）；UI 必须显示 steps_coverage_rate，避免误导。

**验收标准**：
- 错因图在数学作业上默认可用（severity 覆盖率高于阈值）；点击 “!” 能看到清晰的判断标准说明。
- 诊断升级不破坏历史：旧 report 的 meta 保留旧版本号；新版本 report 明确标注 version。

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
