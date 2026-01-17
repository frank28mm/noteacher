# Profile 子账号（家庭-子女）方案：文档对齐与行动项（2026-01-17）

目的：把“Profile 子账号/子女档案（数据隔离）”的新增方案，**同步到所有团队的真源/契约/Backlog/执行计划**，避免出现“各写各的、信息不一致”。

## 1) 已冻结的决策（v1）

- 配额/计费归属：以家长主账号 `user_id` 为计费主体，**家庭共用配额**（不按孩子独立计费）。
- 命名规则：同一 `user_id` 下 `display_name` **必须唯一**（不同家庭可重名）。
- 体验策略：不做“上传前阻断式选择”；只做：
  - 强提示：关键流程持续显示 `提交到：<孩子名>` / `归属：<孩子名>`
  - 可补救：允许把一次作业（submission）移动到另一个 profile

## 2) 需要阅读的“唯一真相来源”（SSOT/契约/计划）

- 方案与开发计划（主文档）：`docs/profile_management_plan.md`
- 前端真源补充（UI/交互口径）：`docs/frontend_design_spec_v2.md`（§1.7）
- 后端契约草案（headers/endpoints/语义）：`homework_agent/API_CONTRACT.md`（Profiles Draft）
- 产品口径（业务/计费/隔离策略）：`product_requirements.md`（§3.3）
- Backlog（拆解条目）：`docs/agent/next_development_worklist_and_pseudocode.md`（FE‑P2‑08 / WL‑P2‑005）
- 当前执行计划（进度面板）：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑F：F‑5）

## 3) 各角色行动项（增援队照此领任务）

### Frontend（H5）
- 实现 Home 右上角 Profile 快捷切换（profiles=2 两个头像并排，当前高亮）。
- 全局请求头注入 `X-Profile-Id`（有 active_profile_id 时）。
- 在拍照/上传/开始批改附近落地强提示：`提交到：<孩子名>`；结果/历史详情落地 `归属：<孩子名>`。
- 增加“移动到其他孩子”入口（调用 move submission）。

### Backend（API）
- 新增 `child_profiles` CRUD（`/api/v1/me/profiles` + `set_default`）。
- 增加 `require_profile_id`（无 header 自动落默认 profile，兼容旧客户端）。
- 读写路径全部按 `(user_id, profile_id)` 过滤/写入（History/DATA/Reports/Chat 等）。
- 增加 `POST /api/v1/submissions/{submission_id}/move_profile`（传错账户可补救）。

### DB / Migration
- 新增 `child_profiles` 表（同一 user 下名字唯一；仅一个 default）。
- 事实表新增 `profile_id`：`submissions/qindex_slices/question_attempts/question_steps/mistake_exclusions/report_jobs/reports`。
- Backfill：为所有 user 创建默认 profile；旧数据回填到默认 profile。

### Workers（qindex/grade/facts/report）
- 以 `submissions.profile_id` 作为事实源，贯穿所有派生写入与读取过滤。
- 确保“生成报告/统计”只聚合当前 `(user_id, profile_id)` 的 submissions/attempts。

### QA / 验收
- 2 个 profile 下：切换后 History/DATA/Reports 严格隔离。
- 用户忘记切换：能通过 move submission 纠正，并且 UI 能清楚提示/入口可达。
- 兼容旧客户端：无 `X-Profile-Id` 时系统仍可用（落默认 profile），但不出现数据串号。

## 4) 同步矩阵（确保“通知到位/更改到位”）

| 领域 | 文档/入口 | 已同步的内容 | 负责人（建议） |
|---|---|---|---|
| 产品口径 | `product_requirements.md` | §3.3：家庭-子女档案与计费/隔离/体验策略 | PM/Owner |
| 前端真源 | `docs/frontend_design_spec_v2.md` | §1.7：Home 头像切换 + 强提示 + 可补救 + header 注入 | FE Lead |
| API 契约 | `homework_agent/API_CONTRACT.md` | Profiles Draft：`X-Profile-Id` + profiles endpoints + move submission | BE Lead |
| Backlog | `docs/agent/next_development_worklist_and_pseudocode.md` | FE‑P2‑08 / WL‑P2‑005 | TL/PM |
| 执行计划 | `docs/tasks/development_plan_grade_reports_security_20260101.md` | WS‑F：F‑5 + Global P1 条目 | TL/PM |
| 方案文档 | `docs/profile_management_plan.md` | 详细分期、DB/worker/前端/验收 | Owner |

