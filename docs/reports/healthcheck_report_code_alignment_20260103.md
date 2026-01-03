# 外部《项目全面体检报告》代码核对与口径对齐（2026-01-03）

> 目的：把“口头/外部总结”里会影响工程决策的断言，用**当前仓库代码**逐条核对；并把出入点同步回“唯一真源/执行计划/契约”，避免后续协作被错误口径误导。
>
> 范围：只核对**可由仓库代码与可复现命令证明**的内容；涉及 Supabase 实库状态（RLS/迁移是否已执行）只给出“需现场查证”的结论。

## 1) 可直接采信（与代码一致）

### 1.1 后端测试文件数
- 断言：`homework_agent/tests` 下约 54 个测试文件
- 结论：✅ 一致
- 证据：`find homework_agent/tests -type f -name 'test_*.py' | wc -l` → `54`

### 1.2 Reports Eligibility 已实现（不依赖 /mistakes）
- 断言：`GET /api/v1/reports/eligibility` 已实现，用于前端 Report 解锁
- 结论：✅ 一致
- 证据：
  - `homework_agent/api/reports.py` 存在 `@router.get("/reports/eligibility", ...)`
  - `homework_frontend/src/hooks/useReportStatus.ts` 调用 `/reports/eligibility`
  - `homework_agent/API_CONTRACT.md` 已记录该接口（6.1）

### 1.3 History/Recent Activity 数据源：Submissions（不看对错）
- 断言：历史记录应来自 `submissions`，不能用 `/mistakes` 推断（会漏掉“全对作业”）
- 结论：✅ 一致（已落地）
- 证据：
  - 后端：`homework_agent/api/submissions.py`（`GET /submissions` + `GET /submissions/{submission_id}`）
  - 前端：`homework_frontend/src/hooks/useSubmissions.ts`、`homework_frontend/src/hooks/useSubmissionDetail.ts`
  - 契约：`homework_agent/API_CONTRACT.md`（6.6/6.7）

### 1.4 复核卡竞态（done 仍需等 review_pending）已按建议对齐
- 断言：前端停止轮询需要同时检查 `review_pending`，否则看不到 `review_pending → review_ready`
- 结论：✅ 一致（前端已实现“Robust Polling”停止条件）
- 证据：`homework_frontend/src/hooks/useGradeJob.ts`：`isFullyComplete = (done|failed) && !hasPendingReviews`

## 2) 需要修正/补充说明（外部报告口径与代码不一致）

### 2.1 “API 端点 = 16 个已实现”不是稳定口径
- 外部断言：API 端点 16 个
- 结论：⚠️ 不一致（当前实际更多；且该数字会随迭代变化）
- 证据（以运行时路由表为准）：
  - `python3 -c "from homework_agent.main import app; ..."` 统计显示当前 `/api/v1/*` **20 条 unique paths**（含 GET/POST 多方法不另计）
- 建议：
  - 文档/汇报避免写“固定端点数”；改为列出“关键端点清单”（以 `homework_agent/API_CONTRACT.md` 为准）。

### 2.2 “前端使用 EventSource + Last-Event-Id 断线重连”不成立（但后端能力存在）
- 外部断言：前端已实现 EventSource/Last-Event-Id 断线重连
- 结论：❌ 前端口径不成立；✅ 后端能力部分成立
- 证据：
  - 前端实现：`homework_frontend/src/components/business/ChatDrawer.tsx` 使用 `fetch(..., { method: 'POST' })` + `ReadableStream` 自行解析 SSE；**没有** `EventSource`、也**没有**发送 `Last-Event-Id` 的逻辑（全仓库前端搜索为空）。
  - 后端实现：`homework_agent/api/chat.py` 接受 `Last-Event-Id` 头，并可重放最近最多 3 条 assistant 消息（仅当前 session）。
- 建议：
  - 契约文档需明确：**服务器支持** `Last-Event-Id`，但**当前 demo 前端未接入**（未来可补）。

### 2.3 “类型完全无 any”不成立（仍有少量 any/类型逃逸）
- 外部断言：前端无 any 滥用、类型完全对齐
- 结论：⚠️ 夸大，需要更谨慎表述
- 证据：
  - `homework_frontend/src/services/types.ts`：`wrong_items: any[]`
  - `homework_frontend/src/services/api.ts`：`(import.meta as any)`
- 建议：
  - 改口径为“核心链路 types 已对齐，仍存在少量 any 作为过渡”。

### 2.4 代码量统计需明确“排除 .venv/node_modules”
- 外部断言：后端 ~29k 行 Python、前端 ~5k 行 TS/React
- 结论：⚠️ 可作为粗估，但需注明统计口径
- 证据（当前仓库粗算）：
  - 后端（排除 `homework_agent/.venv`）：约 **34,650** 行 `.py`
  - 前端（仅 `.ts/.tsx`，排除 `node_modules`）：约 **2,849** 行；若包含样式/配置会更高

## 3) 无法仅凭仓库确认（必须到 Supabase/运行环境查证）

- `supabase/patches/*.sql` 是否已在实库执行（影响 `report_jobs` 锁字段、RLS、facts 表）
- worker 是否使用了 `SUPABASE_SERVICE_ROLE_KEY` 运行（影响 UPDATE/RLS）
- report_worker/facts_worker 是否已在部署环境常驻运行

> 建议：将这些检查项保持在后端唯一执行计划 `docs/tasks/development_plan_grade_reports_security_20260101.md` 的 WS‑B/WS‑C 验收表里，用“可截图/可复现 SQL”做最终确认。

## 4) 已同步到的真源位置（避免多口径）

- 后端执行计划：`docs/tasks/development_plan_grade_reports_security_20260101.md`
- 前端真源：`docs/frontend_design_spec_v2.md`
- API 契约：`homework_agent/API_CONTRACT.md`
- 文档导航入口：`docs/INDEX.md`

