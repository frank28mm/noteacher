# 前端落地执行清单 (Frontend Implementation Checklist)

> **Source of Truth**: 
> - UI/UX: Excalidraw Design & `docs/frontend_design_spec_v2.md`
> - Backend: `docs/tasks/development_plan_grade_reports_security_20260101.md`
> - Source of truth: `docs/frontend_design_spec_v2.md`（NoTeacher UIUX）
> - (Archived) v2.2 history: `docs/archive/frontend_architecture_20260111_v2_2_deprecated.md`

该清单由架构师整理，直接供前端工程师作为 **DoD (Definition of Done)** 使用。

## 1. 全局信息架构 (Information Architecture)

### 1.1 路由结构
- [ ] **Tab 1: Home**
    - `Scanner`: 拍照/相册入口（Floating Action Button）
    - `TaskInProgress`: 全局处理条（仅当 job.status=running 时显示）
    - `RecentActivity`: 最近作业卡片（数据源：`GET /submissions`）
- [ ] **Tab 2: Mistakes (错题本)**
    - `MistakeList`: 按 `Subject` + `Time` 分组（支持 infinite scroll）
    - `MistakeDetail`: 错题详情 Modal（+ "Ask Teacher" 入口）
- [ ] **Tab 3: Reports (学情)**
    - `Dashboard`: 仪表盘 + 历史报告列表
    - `Reporter`: 报告详情页（含趋势/分析/归档）
- [ ] **Tab 4: Mine (我的)**
    - `Profile`: 头像/昵称
    - `Quota`: CP余额/会员标识

### 1.2 全局层级 (Z-Index Strategy)
- [ ] **Level 1 (App)**: Tab页面
- [ ] **Level 2 (Overlay)**: Camera / Image Preview / Grading FullScreen
- [ ] **Level 3 (Modal)**: 题目详情 / 错题详情
- [ ] **Level 4 (Portal)**: **Chat Drawer** (必须最顶层，避免层级遮挡)

---

## 2. 核心状态管理 (State Stores)

使用 Zustand + React Query 分离 UI 态与服务端态。

- [ ] **`useTaskStore` (UI State)**
    - 管理当前 `upload_id` / `job_id` / `scanning_status`
    - 负责 Home 页 "TaskInProgress" 的显隐逻辑
- [ ] **`useSubmissionStore` (Server State)**
    - 缓存 `submissions` 列表与详情（快照）
    - 支持 `invalidateQueries` 实现列表刷新
- [ ] **`useChatStore` (Session State)**
    - 维护 `active_session_id`
    - 管理 `focus_item_id` (当下正在问哪道题)

---

## 3. 关键业务链路 (Critical Flows)

### 3.1 拍照 → 批改 (Scan-to-Learn)
- [ ] **Input**: 支持 `input capture="environment"` (相机) 与 `input multiple` (相册) 混合上传。
- [ ] **Pre-upload**: 选中即生成本地 ObjectURL 缩略图，填补上传请求的空窗期 (200ms)。
- [ ] **Trigger**:
    - `POST /api/v1/uploads` (FormData 循环 append files) -> 获 `upload_id`
    - `POST /api/v1/grade` (Header: `X-Force-Async: 1`) -> 获 `job_id`
- [ ] **Polling**:
    - 间隔策略：2s -> 5s -> 10s (动态降频)
    - 停止条件：`(status=done/failed) AND (无 review_pending 卡片)`

### 3.2 渐进式披露 (Progressive Disclosure)
- [ ] **Layer 1 (占位)**: 轮询到 `question_cards` 有数据，立即渲染灰色骨架卡（显示题号）。
- [ ] **Layer 2 (判定)**: 监听 `page_done` 事件，批量翻转该页卡片为 ✅/❌。
- [ ] **Layer 3 (复核)**: 针对 `review_pending` 卡片持续轮询，直到变为 `review_ready`。

### 3.3 错题与辅导 (Mistakes & Chat)
- [ ] **Context**: 进入 Chat 必须带 `submission_id` + `item_id`。
- [ ] **Rehydrate**: 历史作业点击 "Ask Teacher"，若 session 过期自动使用 `submission_id` 重建会话。
- [ ] **UI**: Chat Drawer 必须支持 LaTeX 公式渲染 (Katex)。

---

## 4. 报表与数据 (Reports & Archive)

### 4.1 趋势与统计 (Reporter UI)
> 后端支持状态：**已规划 (WS-C C-7)**，数据源将位于 `reports.stats.trends`。

- [ ] **Filters (Select/Dial)**:
    - **周期**: 支持 `3天 / 7天 / 30天` (映射后端 `window_days`)。**暂不支持自定义日期**。
    - **学科**: `Math / English` (严格过滤，不混排)。
- [ ] **Charts (Recharts)**:
    - **薄弱知识点 (Line)**: 渲染 `trends.knowledge_top5` (5条曲线)。
    - **错因分布 (Line)**: 渲染 `trends.cause_top3` (3条曲线)。
- [ ] **Mastery Matrix**: 渲染 `stats.type_difficulty` (题型x难度矩阵)。

### 4.2 知识归档 (Data Archive)
- [ ] **Structure**: 展示 `Subject -> Knowledge Category -> Items` 层级。
- [ ] **Action**: 错题详情页增加 "OK (Mastered)" 按钮 -> 调用归档接口 -> 移出错题本。

---

## 5. 待确认问题答复 (Decisions)

1.  **报告周期需自定义吗？**
    *   **决策**: **Phase 1 不做自定义**。仅支持 `3/7/30` 天预设。后端 `development_plan` (C-7) 明确指出初期采用 Bucket 聚合，自定义日期复杂且 ROI 低。
2.  **报告按学科切换吗？**
    *   **决策**: **必须切换**。前端需在报告页顶部提供 Subject Switcher (`Math | English`)。不同学科的知识点体系（Tags）完全不同，混排无法分析。

---

## 6. 开发优先级 (Phase 1)
1.  **P0**: 完成 Home -> Upload -> Grade -> Review 核心闭环 (含渐进式卡片)。
2.  **P1**: 错题本 (Mistakes) 与 Chat Drawer (含 Rehydrate)。
3.  **P2**: 报表 (Reports) 与 趋势图 (需等待后端 output `trends` 字段)。
