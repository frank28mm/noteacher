# 三层渐进披露（Question Cards）实施说明（供前后端对齐）

> 目标：把“等待批改”从黑盒等待变成**秒级可见、逐步变清晰、可中途交互**的过程。
>
> 本文是给前端/后端工程师的对齐文档；唯一执行计划仍以 `docs/tasks/development_plan_grade_reports_security_20260101.md` 为准。

## 1) 核心 UX：Three-Layer Progressive Disclosure

### Layer 1：占位卡（Placeholder Cards，秒级反馈）
- 用户上传完成后，UI 立即展示“已检测到 N 道题”的卡片列表（灰色/占位态）
- 这些卡片不表达对错，只表达**客观事实**（题号、页码、是否未作答）

### Layer 2：判定卡（Verdict Cards，分批翻转）
- 当某一页完成（LLM 聚合结束）时，**该页的卡片批量更新**为“✅/❌/⚠️”
- 用户无需等待全量页完成，即可点卡片进入详情或开始辅导交互

### Layer 3：复核卡（Review Cards，锦上添花）
- 仅对 `visual_risk / uncertain / wrong` 的题，触发更重的视觉证据链（切片/重看）
- 卡片从“可能”升级为“证据更充分/已复核”，同时保持可解释性与可审计

> 现实约束：当前主链路的判定产出以“页”为粒度（每页一次 LLM 聚合）。因此在不大幅增加成本前提下，最稳落地是“页完成后批量补全该页卡片”。真正“题粒度逐题判定”属于后续增强（仅对错题/不确定题启用，避免 token/失败率暴涨）。

实现约束（本轮落地）：
- Layer 3 的复核不阻塞 grade：由独立 worker 异步执行（更新同一个 `job:{job_id}` 的 `question_cards`）。
- 默认只复核“视觉风险 + verdict_uncertain/needs_review”的少量题（每页最多 N 条；通过 env 控制）。

## 2) 后端对前端的最小数据契约（Question Cards）

前端工程师提出的最小 5 字段（✅ 采纳）：

- `item_id: string`（必需）  
  - 前端列表 `key`，用于“局部更新/翻转”，避免全列表闪屏。
  - **稳定性要求**：同一次 submission 内，`item_id` 必须稳定（占位→判定→复核都用同一 ID）。
- `question_number: string`（必需）  
  - 题号（如 `"1"`、`"2(1)"`），用于卡片角标与路由。
- `page_index: int`（必需）  
  - 0-based（第 1 页为 0），用于页分组/动画。
- `answer_state: enum`（必需）  
  - 推荐值域：`"blank" | "has_answer" | "unknown"`  
  - **语义**：只表示“是否作答”的客观事实，不做“不会/遗忘”等动机归因。
- `question_content: string`（可选但强烈建议）  
  - 建议为题干前 10–20 个字（或一行），用于建立“识别可信度”。

推荐的可选字段（便于后续扩展，不影响最小闭环）：
- `card_state: enum`：`"placeholder" | "verdict_ready" | "review_ready"`（用于前端动效与状态机）
- `verdict: enum`：`"correct" | "incorrect" | "uncertain"`（保持现有判定枚举，不新增 `"unattempted"`；空题用 `answer_state=blank` 表达）
- `reason: string`（错题/待确认原因）
- `needs_review: bool`（与现有风控一致）
- `knowledge_tags: string[]`（用于后续“学习报告/薄弱点”）
- `updated_at: string(ISO)`（前端可用于“新结果到达”的动画触发）

## 3) ID 规则（必须统一）

为保证“占位卡 → 判定卡 → 复核卡”的稳定更新，推荐：

- `item_id = "p{page_no}:q:{question_number}"`（page_no 从 1 开始，question_number 原样）
- 若出现跨页题号冲突（例如两页都有第 1 题），后端需要消歧：
  - `question_number` 允许变体：`"{qn}@p{page_no}"`（示例：`"1@p2"`）
  - 同时 `item_id` 保持与 page_no 一致（示例：`"p2:q:1"`）

## 4) 数据来源与生成时机（后端实现要点）

### 4.1 Layer 1（占位卡）的数据来源
- 来自 OCR/识别原文（vision_raw_text）解析出的题目结构（题号/题干/学生作答）
- 由后端在 **LLM 聚合开始前** 尽早写入（减少“黑盒等待”）

### 4.2 Layer 2（判定卡）的数据来源
- 来自每页 LLM 聚合结果（verdict/reason/judgment_basis/knowledge_tags）
- 每页完成时批量更新该页卡片（支持“逐页翻转”）

### 4.3 Layer 3（复核卡）的数据来源
- 来自切片/重看（qindex slices / VFE visual_facts）
- 仅对少量高风险题触发，避免成本与失败率上升

## 5) 接口与事件模型（建议）

### 5.1 `GET /jobs/{job_id}`（已有：轮询）
在现有 `total_pages/done_pages/page_summaries` 基础上，补充：
- `question_cards`：轻量数组（可在 `status=running` 返回，支持“追更模式”）

示例（running，已出占位卡 + 第 1 页判定卡）：
```json
{
  "status": "running",
  "total_pages": 3,
  "done_pages": 1,
  "page_summaries": [{"page_index": 0, "wrong_count": 2, "uncertain_count": 1, "needs_review": true}],
  "question_cards": [
    {"item_id":"p1:q:1","question_number":"1","page_index":0,"answer_state":"has_answer","question_content":"两条平行线被…","card_state":"verdict_ready","verdict":"correct"},
    {"item_id":"p1:q:2","question_number":"2","page_index":0,"answer_state":"blank","question_content":"如图，已知…","card_state":"placeholder"},
    {"item_id":"p2:q:1","question_number":"1@p2","page_index":1,"answer_state":"has_answer","question_content":"…","card_state":"placeholder"}
  ]
}
```

> 轮询策略：Demo/前端可以继续用 polling；后续如要更丝滑，可引入 SSE/WebSocket 推送，但不是本轮必选。

### 5.2 时间展示口径（解决“时间不准”）
- 前端不要用 JS 自己估算 wall time（后台 Tab 会降频导致虚高）
- 展示用后端字段：
  - `job.elapsed_ms`（整单真实执行时间）
  - `page_summaries[].page_elapsed_ms`（逐页真实执行时间）

## 6) 分工（可并行推进）

### 后端工程师（我负责）
- **接口契约**：在 `GET /jobs/{job_id}` 的返回中，补齐/持续更新 `question_cards[]`（`status=running` 也要可返回）。
- **Layer 1（占位）**：尽早产出题号列表（每页开始后尽快可见），写入 `card_state="placeholder"`。
- **Layer 2（判定）**：每页 LLM 聚合完成后，批量更新该页卡片为 `card_state="verdict_ready"`，补齐 `verdict/reason/needs_review`（可选字段）。
- **Layer 3（复核）**：仅对 `uncertain/wrong/visual_risk` 的题补齐复核状态（后续增强，不阻塞本轮 Demo）。
- **空题语义**：产出 `answer_state=blank|has_answer|unknown` 的客观标记；空题不再写成“无法确认原因”（UI 可单列为“未作答”）。
- **稳定 ID**：提供稳定 `item_id` 规则与跨页消歧规则（保证“占位→翻转→复核”的局部更新不闪屏）。
- **时间口径**：在 job 状态里持续输出 `elapsed_ms/page_elapsed_ms`（前端不自行计时）。

后端实现位置（便于工程师快速开工）：
- Worker：`homework_agent/workers/grade_worker.py`（生成/增量更新 `question_cards`）
- Job 存储：`homework_agent/services/grade_queue.py`（初始化 job payload，字段透传到 cache）
- Job 查询：`homework_agent/api/session.py`（`GET /jobs/{job_id}` 直接返回 cache dict，无需额外改动）

### 前端工程师（你负责）
- **追更模式**：轮询 `GET /jobs/{job_id}`（`status=processing/running/done`），以 `item_id` 做局部更新。
- **占位卡**：`question_cards[]` 出现即渲染占位态（灰色），不必等待 `result`。
- **翻转动画**：当卡片从 `card_state="placeholder"` 变为 `verdict_ready` 时触发翻转动画。
- **空题样式**：当 `answer_state="blank"` 时渲染“未作答”（灰色虚线框），不归入“错题”卡片样式。
- **逐页分组**：按 `page_index` 分组展示（支持“第 1 页先出结果，第 2 页继续追更”）。
- **中途进入辅导**：允许用户在部分完成时进入辅导；UI 明示“当前仅基于已完成页回答”（后端已在系统提示中强制免责声明）。

## 7) 验收标准（DoD）
- 上传完成后 ≤ 1 次轮询内出现占位卡列表（非空）
- 每页完成后 ≤ 1 次轮询内，该页卡片状态批量翻转为 verdict
- 空题卡片标记为 `answer_state=blank`，不计入错题/待确认（或单列统计）
- 时间展示使用后端 elapsed（前端不再出现“后台挂起导致 700s”的误导）
