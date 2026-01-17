# 家庭-子女（Profile）账户切换：技术方案与开发计划（v1）

本文档用于落地“一个家长主账号（计费主体）下多个子女档案（Profile），并支持一键切换数据视图”的功能。  
已确认决策：**配额/计费归属主账号（user_id），家庭共用配额**。

---

## 1. 目标与非目标

### 1.1 目标（v1）
- 家长主账号 `user_id` 下可管理多个子女 Profile（至少支持 2 个）。
- 首页右上角提供**醒目的 Profile 快捷切换**（两个头像按钮；多于 2 个时通过展开/弹框选择）。
- 全站数据隔离维度新增 `profile_id`，切换后只展示对应 Profile 的数据（历史记录、错题、报告、档案等）。
- 强提示：在拍照/上传/批改关键流程中持续显示“当前 Profile”，并在“提交/开始批改”处明确提示“提交到：xxx”。
- 可补救：允许把一次作业（submission）从 Profile A 移动到 Profile B（纠正传错账户）。

### 1.2 非目标（v1 不做）
- 不做“强制阻断式预防”（例如每次上传前强制弹出选择 Profile）。
- 不做“每个孩子独立钱包/独立计费”（v1 家庭共用）。
- 不要求把登录注册流程立即接入（UI 调整优先；登录集成可在后续 Phase 做）。

---

## 2. 核心概念与约束

### 2.1 身份层级
- `user_id`：家长主账号（认证主体、计费主体、数据主归属）。
- `profile_id`：子女档案（数据隔离视图主体）。

### 2.2 命名唯一性
- **同一 `user_id` 下 `display_name` 必须唯一**（避免家长自己也分不清；UI 切换风险极高）。
- 全库允许重名（不同家庭可有相同 `display_name`）。

### 2.3 Header 协议
- 所有业务请求（前端 → 后端）统一携带：
  - `X-User-Id`（开发态）或 `Authorization: Bearer ...`（登录态）
  - `X-Profile-Id: <profile_id>`（当前子女）

---

## 3. 数据模型（DB 变更）

### 3.1 新增表：`child_profiles`

建议表结构（可扩展，但 v1 字段尽量克制）：
- `profile_id uuid PK default uuid_generate_v4()`
- `user_id text not null references users(user_id) on delete cascade`
- `display_name text not null`
- `avatar_url text null`
- `grade_level text null`（可选）
- `birth_year int null`（可选）
- `is_default boolean not null default false`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

约束/索引：
- `unique(user_id, display_name)`
- 需要保证“每个 user 仅一个默认 Profile”：
  - 方案 A（推荐，Postgres）：partial unique index `unique(user_id) where is_default = true`
  - 方案 B：写入时事务内先清其它 default，再置当前为 default（仍建议加索引兜底）

### 3.2 现有表新增列：`profile_id`

以下表新增 `profile_id`（uuid/text 取决于你们约定，建议 uuid 文本化传输一致）：
- `submissions`
- `qindex_slices`
- `question_attempts`
- `question_steps`
- `mistake_exclusions`
- `report_jobs`
- `reports`

索引建议：
- 对查询入口较多的表加组合索引：`(user_id, profile_id, created_at desc)` 或 `(user_id, profile_id, ...)`

### 3.3 迁移与回填（Backfill）

目标：保证“旧数据不丢、默认可用”。

1) 为所有已有 `users` 创建默认 Profile（而不是从 `submissions` 反推，避免漏掉未上传过的账号）  
2) 将历史业务数据的 `profile_id` 回填为该用户的默认 Profile  
3) 确保后端逻辑：新写入没有 profile 也会落到 default（兼容旧客户端）

---

## 4. 后端改造（API / 逻辑 / Worker）

### 4.1 Profile 解析：`require_profile_id`

新增 `require_profile_id(user_id, x_profile_id)`：
- 若 header 提供 `X-Profile-Id`：
  - 校验该 profile 属于当前 user（否则 403）
  - 返回该 profile_id
- 若 header 未提供：
  - 返回该 user 的默认 profile（`is_default=true`）
  - 若不存在默认 profile：自动创建一个默认 profile（兜底）

> 注意：由于 v1 不做强制阻断预防，为了兼容旧页面/旧客户端，“无 header 时自动走 default”是必要的。

### 4.2 Profile CRUD（建议放在 `/api/v1/me`）

新增端点（建议）：
- `GET /api/v1/me/profiles`：列出 profiles + 当前默认 profile_id
- `POST /api/v1/me/profiles`：创建 profile（校验 display_name 唯一）
- `PATCH /api/v1/me/profiles/{profile_id}`：更新 display_name/avatar/grade 等
- `POST /api/v1/me/profiles/{profile_id}/set_default`：设置默认（用于切换时同步写 DB）
- `DELETE /api/v1/me/profiles/{profile_id}`：删除（限制：不能删除最后一个；删除默认时自动迁移默认到另一个）

### 4.3 业务 API 全面接入 profile 维度

影响面：
- 所有 `require_user_id()` 的入口都要补：`profile_id = require_profile_id(user_id, x_profile_id)`
- 写入：所有写入业务数据的地方必须写 `profile_id`
- 读取：所有按 user_id 查询的列表/详情必须加 `profile_id` 过滤（避免混在一起）

重点路由（优先级从高到低）：
- `/uploads`、`/grade`、`/submissions`、`/reports`、`/mistakes`、`/chat`

### 4.4 Worker 链路：profile_id 贯穿

写入源头建议：**以 `submissions.profile_id` 为事实源**，worker 能从 submission snapshot 取 profile_id，避免“某一段忘记传”。

链路改造要点：
- upload/grade 创建 submission 时写入 profile_id
- facts_worker 写 `question_attempts/question_steps` 时写入 profile_id
- qindex_worker 写 `qindex_slices` 时写入 profile_id
- report_worker 读 attempts/reports 时按 `(user_id, profile_id)` 聚合

### 4.5 “传错账户”补救：移动 submission

新增端点（建议）：
- `POST /api/v1/submissions/{submission_id}/move_profile`
  - body：`{ "to_profile_id": "..." }`
  - 校验：`to_profile_id` 属于当前 user
  - 执行：将该 submission 及其派生事实迁移到新 profile

迁移范围（v1 建议）：
- `submissions.profile_id`
- `question_attempts.profile_id`
- `question_steps.profile_id`
- `qindex_slices.profile_id`
- `mistake_exclusions.profile_id`（同 submission/item 维度）

对报告（reports）处理建议（v1）：
- 不自动迁移已生成的历史 report（它可能聚合了多个 submission；自动改写风险高）
- 在 move_profile 成功后：
  - 提示用户“报告需重新生成才能体现归属变更”
  - 可提供快捷入口：为目标 profile 触发一次 report_job（可选）

---

## 5. 前端改造（UI / 状态 / 强提示）

### 5.1 头像切换（首页右上角）

设计目标：**足够醒目，一眼看出当前在哪个孩子**。

交互方案：
- profiles=1：显示 1 个头像按钮（当前 profile），点击仅弹出“当前：xxx”（无切换、无登出）。
- profiles=2：显示 2 个头像按钮并排（当前高亮 ring + 轻动画），点击任意头像立即切换。
- profiles>2：显示当前 + 次级头像 + “更多(… )”按钮，点击打开 Popover 列表选择。

视觉建议：
- 每个 profile 分配固定颜色（例如 ring/角标），与“提交到：xxx”提示一致，降低误操作。

### 5.2 全局状态与 Header 注入

新增 ProfileStore（Zustand 或 Context，和现有状态风格保持一致）：
- `profiles: Profile[]`
- `activeProfileId: string | null`
- `fetchProfiles()`
- `setActiveProfile(id)`：更新 localStorage +（可选）调用 set_default endpoint

axios 拦截器：
- 在 `apiClient` 请求头自动注入 `X-Profile-Id = localStorage.active_profile_id`（若为空则不注入，由后端 default 兜底）

### 5.3 强提示（只做强提示 + 可补救）

在以下页面加入“当前 profile”展示（不阻断、不弹强制选择框）：
- 拍照页（Camera/Scan）：顶部或底部显眼展示 `当前：大儿子` + 小切换入口
- 上传页（Upload）：上传按钮上方显示 `提交到：大儿子`（可点切换）
- 批改结果页/历史详情：展示 `归属：大儿子` + `移动到其他孩子` 按钮（触发 move_profile）

### 5.4 Mine（我的）页面：子女管理入口
- 入口：`管理子女`（列表、添加、编辑头像/名称、删除）
- v1 只需最小字段：名称 + 可选头像

---

## 6. 验收标准（Acceptance Criteria）

### 6.1 数据隔离
- 切换 profile 后：
  - 历史记录/错题/报告列表均只展示该 profile 的数据
  - 新上传的 submission 必须写入当前 profile_id

### 6.2 强提示
- 上传/开始批改按钮附近必须能清晰看到 `提交到：<profile_name>`。
- 首页切换头像一眼可见当前 profile（高亮状态明显）。

### 6.3 可补救
- 对任意 submission，可从详情触发“移动到其他孩子”，迁移后：
  - submission 与其 attempts/steps/slices/exclusions 的归属同步变更
  - 在目标 profile 的历史记录能看到该 submission

### 6.4 兼容性
- 未注入 `X-Profile-Id` 的旧页面/旧请求仍能工作（落到 default profile）。

---

## 7. 分阶段开发计划（建议排期）

> 不阻塞你当前“页面 UI 调整”的节奏：先做后端兼容层 + 默认 profile 兜底。

### Phase 0（设计确认，0.5 天）
- 确认 DB 字段类型（uuid/text）与索引策略
- 确认“同一家庭 display_name 唯一”与默认策略

### Phase 1（后端兼容层，2–3 天，P0）
- migration：新增 `child_profiles` + 相关表加 `profile_id` + 索引
- backfill：为 `users` 创建默认 profile，并回填历史数据 profile_id
- 后端：实现 `require_profile_id()`；业务读取/写入补 profile_id

### Phase 2（写入链路与 worker，2–3 天，P0）
- upload/grade 写入 submissions.profile_id
- qindex/facts/report worker 全链路写入/读取 profile_id
- report 统计按 profile 维度聚合（`(user_id, profile_id)`）

### Phase 3（前端切换 + 强提示，1–2 天，P1）
- 首页头像多按钮切换（2 子女场景优先）
- ProfileStore + axios 注入 `X-Profile-Id`
- Camera/Upload/Result/History 加 “当前 profile”强提示

### Phase 4（可补救 move_profile，1–2 天，P1）
- 后端 move_profile endpoint + 数据迁移逻辑
- 前端 submission 详情加 “移动到其他孩子”

### Phase 5（登录注册集成，后续，P2）
- Login 页面接 `/auth/sms/*`
- 首次登录引导创建两个孩子（或至少一个）

---

## 8. 风险与对策

- 报告（reports）历史聚合迁移复杂：v1 不自动迁移 reports，仅提示重新生成。
- 旧数据回填量大：先在 dev/staging 验证 backfill 脚本与耗时，再上生产。
- 多 profile 下“忘切换”的误操作：用强提示（当前 profile + 提交到谁）+ move_profile 兜底降低损失。

