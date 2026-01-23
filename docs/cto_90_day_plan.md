# CTO 90 天计划（作业检查大师 / Homework Checker Agent）

> 目标：把当前 Phase 1 的“可用后端”推进到“可规模化迭代、可上线运营、可持续评估”的状态。

## 0. 北极星指标（每周追踪）

- 质量：`replay` 结构稳定（CI 全绿），`uncertain_rate`/`needs_review_rate` 可控且可解释
- 体验：`/grade` P95 < 60s（同步场景），`/chat` 首 token P95（`chat_llm_first_output`）持续下降
- 成本：单次批改与单轮 chat 的 token/费用有上限护栏（`RunBudget`）并可回放
- 稳定性：5xx < 1%，外部依赖失败可降级（vision/ocr/qindex/redis）

## 1. Week 1（接手稳态化）

- [x] 工程健康：本地/CI 完整验证链路（compile/test/observability/security/replay/baseline）
- [x] **Schema 对齐（P0）**：以 `supabase/schema.sql` 为当前真源，对齐 reports/report_jobs 口径并补齐缺失表
- [x] 依赖治理：锁定“可复现安装”的依赖集合，CI 增加 `pip check` 防止依赖漂移
- [x] 契约对齐：文档/实现口径统一（SSE、会话 TTL、轮次策略、relook 边界）
- [x] 运行手册：补齐上线必需的 env/开关表（prod 安全要求、CORS、auth、redis 必选项）
- [x] 数据闭环（MVP）：历史错题查询 + 排除/恢复 + 知识点基础统计
  - 实施方案：`docs/archive/design/mistakes_reports_learning_analyst_design.md`

## 2. Week 2–4（走向可上线）

- [x] 数据闭环最小落地：
  - [x] Submission 持久化：`/uploads` 与 `/grade` 结果入库（Postgres）可按用户/时间查询
  - [x] 错题本产品化：支持按 `user_id` 聚合历史错题、排除/恢复误判、基础统计
  - [x] 报告链路打底：引入 `report_jobs/reports`（异步生成、可查询、可重跑）
  - [x] 报告解锁口径统一（Eligibility）：Demo 用“≥3 次 submission”快速联调
  - [x] 会话/切片 TTL 策略固化：明确“短期数据”和“长期数据”的清理职责边界
- [x] E2E 自动化：
  - [x] CI 保留 offline replay 门禁；新增“无外部依赖”的 E2E 冒烟
  - [x] Live quality gate 作为手动 workflow
  - [x] **/grade 快路径默认（当前固定）**：`AUTONOMOUS_PREPROCESS_MODE=qindex_only` + `GRADE_IMAGE_INPUT_VARIANT=url`
- [x] Demo 体验（多页作业）：
  - [x] 多页逐页可用：第 1 页先出摘要，不等待全量（方案 A：单 job + partial 输出）
  - [x] 可选进入辅导：用户点击“进入辅导（本页）”才进入 chat
  - [x] 复核卡（Layer 3）：少量视觉高风险题异步复核
- [x] 生产形态：
  - [x] Redis 必选开关（`REQUIRE_REDIS=1`）与 worker 部署拓扑落地
  - [x] Metrics/Logs/Tracing 统一采集与告警阈值

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

### 架构说明（2026-01-22 更新）

**部署架构**：阿里云 ACK（托管 K8s）+ ECI（弹性容器实例）+ PolarDB for Supabase
- **数据库**：PolarDB for Supabase（兼容 Supabase API，提供 PostgREST、Auth、Realtime、Storage）
- **K8s 集群**：ACK 托管集群 + HPA（API）+ KEDA（Workers）
- **弹性扩容**：ECI 承接 burst 流量（grade_worker）
- **对象存储**：PolarDB Storage 内置（无需额外 OSS）

详见：`docs/tasks/development_plan_grade_reports_security_20260101.md` § WS‑D

## 5. 当前开放问题（需要产品/业务共同决策）

- ~~登录体系与用户隔离~~ ✅ 已完成：手机号验证码登录 + JWT + Profile 子账户
- ~~题目"全对也可聊"的产品边界~~ ✅ 已完成：Chat Rehydrate 支持历史错题复习
- 是否引入 BFF：移动端直连 SSE 还是通过 BFF 统一连接管理与鉴权？
- 部署 IaC：ACK + ECI + PolarDB 的 YAML/ Helm Chart 配置落地
