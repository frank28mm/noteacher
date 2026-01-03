# Backend Gaps Implementation Plan (Stitch UI Alignment)

> 目的：把 Stitch UI / `docs/frontend_design_spec_v2.md` 里**确认缺失的后端能力**收敛成一份可执行清单，并保证与后端“唯一执行计划”一致。
>
> 唯一执行计划：`docs/tasks/development_plan_grade_reports_security_20260101.md`
>
> 前端唯一真源：`docs/frontend_design_spec_v2.md`
>
> 外部总结口径校对：`docs/reports/healthcheck_report_code_alignment_20260103.md`（遇到“端点数量/SSE 客户端实现/类型全绿”等争议点，以此为准）

---

## 0) 结论摘要（先说清“要不要做”）

- 必须补（P0）：
  - ✅ **Submissions/History 列表接口**：`GET /api/v1/submissions` 已实现（用于首页 Recent Activity、History 列表的权威数据源）。
  - ✅ **Submissions/History 详情接口（方案 B）**：`GET /api/v1/submissions/{submission_id}` 已实现（快照详情，不重建 job）。
  - ✅ **历史错题“问老师”Rehydrate**：已实现（`POST /api/v1/chat` 支持 `submission_id`，心跳首包返回新 `session_id`）。
  - 不属于缺口（已具备）：
  - **Report 解锁 Eligibility**：`GET /api/v1/reports/eligibility` 已实现（数据源基于 `submissions`，不依赖 `/mistakes`）。
- 暂缓（P2 / 不阻塞 Stitch 主链路）：
  - **Reports 自由日期范围 `start_date/end_date`**：本阶段不做，先用 `window_days`（周期）+ `submission_id`（单次）覆盖 demo/产品路径。

---

## 1) P0：Submissions / History List

### 1.1 目标

- Stitch：Home “Recent Activity” + “View all” + Report Tab 里的历史列表，都需要权威的 submission 列表。
- 口径必须来自 `submissions`（不能用 `/mistakes` 推断，否则“全对作业”会消失）。

### 1.2 建议接口

- `GET /api/v1/submissions?subject=math&limit=20&before=2026-01-03T00:00:00Z`

返回示例（建议字段）：

```json
{
  "items": [
    {
      "submission_id": "upl_xxx",
      "created_at": "2026-01-03T14:48:43Z",
      "subject": "math",
      "total_pages": 3,
      "done_pages": 3,
      "summary": {
        "total_items": 18,
        "wrong_count": 2,
        "uncertain_count": 1,
        "blank_count": 0,
        "score_text": "95/100"
      },
      "session_id": "session_xxx"
    }
  ],
  "next_before": "2026-01-02T00:00:00Z"
}
```

### 1.3 数据来源

- `submissions` 表（按 `user_id` + `subject` + `created_at desc`）
- 允许 `summary` 为空（旧数据/异常数据），前端降级显示“已批改/查看详情”。

### 1.4 验收

- Home Recent Activity 能展示最近 N 次作业（包含全对作业）。
- 点击任意记录能进入 Result Screen（Replay Mode）：
  - 最小实现：前端用 `submission_id` 调 `POST /api/v1/grade`（Scheme A：`upload_id=submission_id`，`images=[]`，`X-Force-Async: 1`）重建 job 并回放。
  - 后续优化：增加 `GET /submissions/{id}` 直接拿快照（可选，不阻塞）。

---

## 2) P0：历史错题 Ask Teacher（Chat Rehydrate）

### 2.1 背景

- 24h TTL 清理的是 Redis 短期缓存（`session/qbank/job/qindex`），不是 `submissions` 持久化快照。
- 用户在错题本点“问老师”不应被迫重新上传。

### 2.2 建议接口与行为

优先选项（改动面小，兼容现有 `/chat`）：

- 扩展 `POST /api/v1/chat` 支持：
  - `submission_id`（= upload_id）
  - `context_item_ids=[item_id]`

后端行为：
- 当 `session_id` 缺失/过期或提供了 `submission_id`：
  - 从 `submissions` 读取该 submission 的 `grade_result`（必要时 `vision_raw_text`）
  - 生成新的 `session_id` + 最小 qbank 写入 Redis（仍 24h TTL）
  - SSE 首包返回新的 `session_id`（前端保存后续继续聊）

### 2.3 验收

- 对 ≥48h 前的 submission，错题详情点击“问老师”能直接对话，不出现“请重新上传/题库快照不存在”。
- 回答必须标注证据边界：仅基于该 submission 的证据；证据不足必须 `uncertain/needs_review`。

---

## 3) P2：Reports 自由日期范围（Deferred）

### 3.1 当前策略（不阻塞 Stitch）

- Demo：单次报告走 `submission_id`（“本次作业报告”）。
- 产品：周期报告走 `window_days`（7/30/90 等预设），并用 `GET /api/v1/reports/eligibility` 控制解锁。

### 3.2 何时再做 `start_date/end_date`

- 当产品前端明确要“任意日期范围”的周报/阶段报告时再加：
  - `POST /api/v1/reports` 支持 `start_date/end_date`
  - `GET /api/v1/reports` 支持按范围查询列表
