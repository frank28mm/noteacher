# 项目落地实施报告 (Project Implementation Report)

> **版本日期**: 2026-01-11
> **文档性质**: 前后端协作开发的**最终契约 (Final Agreement)**。
> **依据**: User Feedback (Point 1-6), Excalidraw Design, `frontend_design_spec_v2.md`, Backend Development Plan (WS-C).

## 1. 核心业务流程与信息架构 (Business Flow & IA)

### 1.1 全局导航架构 (App Structure)
应用采用 **"Tab-based Navigation + Modal Overlays"** 结构。

*   **底部导航栏 (Tabs)**
    1.  **Home (首页)**: 作业入口 + 任务进行时 (TaskInProgress) + 最近动态。
    2.  **Mistakes (错题本)**: 错题聚合（按学科/时间） -> 错题详情。
    3.  **Reports (学情)**: 仪表盘 -> 深度报告详情 (Reporter)。
    4.  **Mine (我的)**: 个人信息、会员权益 (CP/VIP)。

*   **覆盖层级 (Overlays)**
    *   **Level 2**: `Camera / UploadPreview` (全屏覆盖，专注任务)。
    *   **Level 3**: `GradingDetail` (批改结果页，支持多页滑动)。
    *   **Level 4**: `ChatDrawer` (Portal 挂载最顶层，**苏格拉底式辅导**)。

### 1.2 "Scan-to-Learn" 主链路逻辑

1.  **启动与采集 (Start & Capture)**
    *   **入口**: Home 点击 "Scan" 悬浮按钮。
    *   **采集**: 支持 `Camera` (原生 capture) 与 `Album` (多选) 混合。
    *   **极速响应**: 文件选中即生成本地 ObjectURL 缩略图；**不强制** Loading 动画时长 (避免 <500ms 时的闪屏，自然过渡)。

2.  **分析与渐进披露 (Analyzing & Progressive Disclosure)**
    *   **状态**: 进入 `GradingDetail` 页。
    *   **交互**: 顶部显示 Page Tabs (Page 1, 2...)。
    *   **显示逻辑**:
        *   **Layer 1 (T0)**: 立即展示灰色占位卡 (Queston Skeleton)。
        *   **Layer 2 (T+N)**: 当 `page_done`，该页卡片批量翻转为 ✅/❌/⚠️。
        *   **Layer 3 (T+M)**: 风险题异步更新为 `Review Ready`。

3.  **结果查看 (Result View)**
    *   **默认视图 (Mistakes First)**: 优先展示 `Mistakes` (错题/存疑) 卡片，支持左右滑动浏览。
    *   **全量视图 (All Items)**: 提供 `View Toggle` (Switch/Tab) 切换至 **"All"** 视图，此时展示 **Correct (正确)** 和 **Unknown** 题目。
        *   *响应用户 Point 1*: 正确/未知题在 "All" 视图中展示，不默认挤占错题注意力。

4.  **AI 辅导闭环 (AI Tutoring)**
    *   **入口**: 错题详情页 / 结果页卡片。
    *   **上下文 (Context)**: **严格死锁**在当前 `submission_id` + `item_id`。
    *   **记忆 (Memory)**: **按题存储**。用户退出重进该题，必须能看到之前的历史记录 (Rehydrate)。
    *   **引导 (Pedagogy)**: **拒绝直接给答案**。Backend Prompt 需强制执行苏格拉底式引导 (仅提供思路/反问)。

5.  **归档闭环 (Archive & Mastery)**
    *   **动作**: 在错题详情页点击 **"OK (已掌握)"**。
    *   **结果**: 题目从错题本移除，进入 `Archive` (知识档案) 的 "Mastered" 分组。

---

## 2. 前端需求与执行清单 (Frontend Requirements)

直接对接前端开发 (React/Vite)。

### P0: 核心批改链路
- [ ] **上传**: 实现 `FormData` 多文件上传，处理 iOS/Android `capture` 兼容性。
- [ ] **轮询引擎**:
    - 动态降频 (2s->5s->10s)。
    - **停止条件**: `(status=done/failed) AND (无 review_pending)`。
    - **任务恢复**: App 冷启动时检查 localStorage 中的 `active_job_id`，若 running 则恢复轮询面板。
- [ ] **结果页视图**:
    - 实现 `SlideView` (Mistakes) 与 `ListView` (All) 的切换。
    - 渲染 ✅ 正确 / ❌ 错误 / ⚠️ 存疑 / ⬜ 未作答 四种状态卡片。

### P0: AI 辅导 (Chat)
- [ ] **Drawer UI**: 使用 Portal 渲染，支持拖拽关闭，Z-Index 最高。
- [ ] **Chat Logic**:
    - 进房参数: `submission_id` + `item_id`。
    - 历史加载: 首次打开时显示后端返回的 `history_messages`。
    - **边界控制**: 若用户问 "第 2 题怎么做" (跨题)，拦截并返回 "请前往对应题目提问"。

### P1: 报表与趋势 (Reporter)
- [ ] **交互 (Rotary UI)**: 实现点击切换的 "3D / 7D / 30D" 选钮 (Click-to-Rotate)。
- [ ] **筛选**: 顶部必须有 **Subject Switcher** (`Math` | `English`)，且**不提供自定义日期**。
- [ ] **图表 (Trend)**:
    - 渲染 **Knowledge Top5** (5条线) 和 **Cause Top3** (3条线)。
    - 数据源: `reports.stats.trends` (需后端 C-7).

### P1: 知识档案 (Archive)
- [ ] **UI**: 学科分类卡片 (实时显示题目数) -> 下钻至知识点列表。
- [ ] **Action**: 对接 `POST /items/{id}/archive` 接口。

---

## 3. 后端工作与缺口补齐 (Backend Tasks)

### 3.1 报表能力 (C-7 Report Trends)
- [ ] **趋势数据生产**:
    - 在 `report_features` 中新增 `trends` 字段。
    - 规则: `time_window` (3/7/30)。粒度自适应: 点数>15 时按 **3天分桶 (Bucket 3d)** 聚合。
    - 输出: `knowledge_trends_top5` (Tag维度) + `cause_trends_top3` (Severity维度)。

### 3.2 错因体系 (C-9 Severity System)
- [ ] **数据源**: 确保 `question_attempts.severity` 有值 (Calculation/Concept/Format)。
- [ ] **统计**: 在 Report Stats 中聚合 `severity_counts` 供前端饼图使用。

### 3.3 AI 辅导增强 (Chat Memory & Prompt)
- [ ] **记忆持久化**:
    - 调整 `POST /chat` 或新增 `GET /chat/history`。
    - 逻辑: 确保存储 key 为 `(submission_id, item_id)`。
- [ ] **苏格拉底 Prompt**:
    - 修改 System Prompt，增加 Negative Constraints: "禁止直接给出最终答案", "即使有图也不要在 Chat 中重复发送切片(前端已展示)", "引导用户自己思考"。
    - 意图识别: 若用户问 "第 2 题怎么做" (跨题)，拦截并返回 "请点击第 2 题卡片进行提问"。

### 3.4 归档接口 (Archive API)
- [ ] **API**: 新增 `POST /api/v1/items/{item_id}/archive`。
- [ ] **逻辑**: 标记 `question_attempts.is_mastered = true`，使其在错题本查询时被过滤，但仍保留在 Report 统计分母中。

---

## 4. 界面跳转逻辑表 (Visual Transition Table)

| 当前状态 | 用户动作 | 下一状态 | 数据动作 |
| :--- | :--- | :--- | :--- |
| **Home** | Click "Scan" | **Camera/Picker** | - |
| **Preview** | Click "Upload" | **TaskInProgress** (Home) -> **GradingDetail** | POST /uploads + /grade |
| **Grading** (Layer 1) | Page Done (Event) | **Grading** (Layer 2) | 更新 Cards 翻转状态 |
| **Grading** | Click "Mistake Card" | **Detail Modal** | 加载详情 |
| **Detail Modal** | Click "Ask Teacher" | **Chat Drawer** | 加载 History, 建立 Session |
| **Chat** | Click "Close" | **Detail Modal** | 保持 Session, 不清空 History |
| **Grading** | Click "Toggle All" | **Grading** (Grid View) | 展示 Correct/Blank 题目 |
| **Mistakes** | Click "OK (Mastered)" | **Mistakes** | 列表移除该题 (Optimistic UI) |
| **Report** | Click "Rotary 7D" | **Report** (Loading) | GET /reports?window=7 |

---
**确认**: 该报告已涵盖用户反馈的 Point 1-6 及所有补充逻辑。请批准以此为基准进行开发。
