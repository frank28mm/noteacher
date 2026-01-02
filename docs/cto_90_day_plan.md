# CTO 90 天计划（作业检查大师 / Homework Checker Agent）

> 目标：把当前 Phase 1 的“可用后端”推进到“可规模化迭代、可上线运营、可持续评估”的状态。

## 0. 北极星指标（每周追踪）

- 质量：`replay` 结构稳定（CI 全绿），`uncertain_rate`/`needs_review_rate` 可控且可解释
- 体验：`/grade` P95 < 60s（同步场景），`/chat` 首 token P95（`chat_llm_first_output`）持续下降
- 成本：单次批改与单轮 chat 的 token/费用有上限护栏（`RunBudget`）并可回放
- 稳定性：5xx < 1%，外部依赖失败可降级（vision/ocr/qindex/redis）

## 1. Week 1（接手稳态化）

- 工程健康：本地/CI 完整验证链路（compile/test/observability/security/replay/baseline）
- **Schema 对齐（P0）**：以 `supabase/schema.sql` 为当前真源，对齐 reports/report_jobs 口径并补齐缺失表（避免“迁移文件=真源”的误导）
- 依赖治理：锁定“可复现安装”的依赖集合，CI 增加 `pip check` 防止依赖漂移
- 契约对齐：文档/实现口径统一（SSE、会话 TTL、轮次策略、relook 边界）
- 运行手册：补齐上线必需的 env/开关表（prod 安全要求、CORS、auth、redis 必选项）
- 数据闭环（MVP）：历史错题查询 + 排除/恢复 + 知识点基础统计（为“复盘→报告”铺路）
  - 实施方案（Design Doc）：`docs/archive/design/mistakes_reports_learning_analyst_design.md`

## 2. Week 2–4（走向可上线）

- 数据闭环最小落地：
  - Submission 持久化：`/uploads` 与 `/grade` 结果入库（Postgres）可按用户/时间查询
  - 错题本产品化：支持按 `user_id` 聚合历史错题、排除/恢复误判、基础统计（按 `knowledge_tags`）
  - 报告链路打底：引入 `report_jobs/reports`（异步生成、可查询、可重跑），为“学情分析师 subagent”提供落点（实施方案：`docs/archive/design/mistakes_reports_learning_analyst_design.md`）
  - 会话/切片 TTL 策略固化：明确“短期数据”和“长期数据”的清理职责边界
- E2E 自动化：
  - CI 保留 offline replay 门禁；新增“无外部依赖”的 E2E 冒烟（stub LLM/Vision）
  - Live quality gate 作为手动 workflow（已有 `live_quality_gate.yml`），扩大样本与阈值口径
  - 性能实验口径（/grade）：日常迭代每个 variant 跑 N=5（看 `p50 + max + 失败率/needs_review率`）；做默认策略/验收结论时再补一轮 N=5（两轮合并≈N=10 后看 `p50/p95`）
  - **/grade 快路径默认（当前固定）**：
    - 默认：`AUTONOMOUS_PREPROCESS_MODE=qindex_only` + `GRADE_IMAGE_INPUT_VARIANT=url`
    - 策略：先 OCR（可缓存）→ 文本聚合（Ark 推理模型），避免 deep-vision 在快路径里长时间思考/拉图
    - 证据：`docs/reports/grade_perf_url_n3_fast_finalize_12000_20260102.md`（同图重复可复现）
    - 视觉题触发规则与验证（A‑5）：`docs/reports/grade_perf_visual_validation_20260102.md`
  - Demo 体验（多页作业）：
    - 多页逐页可用：第 1 页先出摘要，不等待全量（方案 A：单 job + partial 输出）
    - 可选进入辅导：用户点击“进入辅导（本页）”才进入 chat；chat 只基于已完成页回答并标注范围
- 生产形态：
  - Redis 必选开关（`REQUIRE_REDIS=1`）与 worker 部署拓扑落地（grade/qindex worker）
  - Metrics/Logs/Tracing 统一采集与告警阈值（先最小集：错误率/延迟/成本/队列堆积）

## 3. Month 2（体验与质量提升）

- confidence 阈值校准：
  - 采样 telemetry + 人工 reviewer 复核，形成“可解释的阈值更新流程”
  - 将阈值变更纳入 baseline 与 PR 模板，保证可回滚
- 学情分析师 subagent：
  - 定义报告 JSON schema（可审计、可追溯、可回放）
  - 基于历史 submissions + mistake_exclusions 生成报告（先 MVP：知识点薄弱、错误类型画像、复习建议、7/14 天计划）
  - 为 subagent 建立回归样本与评估口径（避免“越改越玄学”）
- 大文件拆分与边界收敛：
  - `homework_agent/api/chat.py`、`homework_agent/services/llm.py` 按职责拆分（不改行为先）
  - 明确 VFE relook 默认策略与 fail-closed 触发条件（产品与工程共识）
- 题目定位体验闭环：
  - qindex 产物（bbox/slice）与 `question_candidates` 的 UI 交互协议固化

## 4. Month 3（规模化与运营准备）

- 成本与并发治理：并发限流（vision/llm）、队列优先级、缓存命中策略、超大图压缩策略固化
- 安全与合规：上线前最小审计（PII、Prompt Injection、RLS、signed URL、审计日志）
- 发布节奏：灰度/回滚策略、故障演练（外部 provider 限流/超时/断线）

## 5. 当前开放问题（需要产品/业务共同决策）

- 登录体系与用户隔离：何时从 `X-User-Id`/DEV 兜底切换到真实 auth？RLS 范围如何收口？
- 题目“全对也可聊”的产品边界：是否允许“非本次 submission”问题进入对话？
- 是否引入 BFF：移动端直连 SSE 还是通过 BFF 统一连接管理与鉴权？
