# Homework Agent API Contract

## 1. 概览 (Overview)

本契约定义前端（React）与后端（FastAPI）之间的REST API通信协议，支持同步/异步批改和SSE流式聊天辅导。

### Base URL
- **Development**: `http://localhost:8000`
- **Production**: `https://api.homework-agent.example.com`

### 通用规范
- **Content-Type**: `application/json`
- **认证**: Bearer Token (后续扩展)
- **字符编码**: UTF-8
- **时区**: UTC (ISO 8601)
- **幂等键**: 使用 HTTP 头 `X-Idempotency-Key`（推荐 UUIDv4）；请求体不再接受 `idempotency_key` 字段。

---

## 2. 数据模型 (Data Models)

### 2.1 图片引用 (ImageRef)
```typescript
{
  "url": "https://cdn.example.com/image.jpg",  // 可选，推荐。需公网 HTTP/HTTPS，禁止 localhost/127
  "base64": "data:image/jpeg;base64,/9j/4AAQ..."  // 可选，兜底。必须是 Data URL（保留 data:image/...;base64, 前缀）；大图建议改用 URL
}
```

### 2.2 归一化坐标 (BBoxNormalized)
```typescript
{
  "coords": [ymin, xmin, ymax, xmax]  // 归一化 [0-1]，左上原点，y 向下
}
```

### 2.3 判分模式 (SimilarityMode)
`"normal"`（默认，阈值约 0.85，无关键术语硬性校验） | `"strict"`（阈值约 0.91，LLM 自动提炼 1-3 个关键术语，需相似度达标且术语出现）。

### 2.4 错题项 (WrongItem)
```typescript
{
  "page_image_url": "https://cdn.example.com/page1.jpg",
  "slice_image_url": "https://cdn.example.com/slice123.jpg",  // 可选：整题切片
  "page_bbox": {"coords": [0.2, 0.3, 0.5, 0.8]},             // 可选：整题区域 bbox（MVP 允许偏大）
  "review_slice_bbox": {"coords": [0.2, 0.3, 0.4, 0.5]},      // 可选：题干+作答组合切片 bbox（后续可用）
  "question_bboxes": [{"coords": [0.2, 0.3, 0.5, 0.8]}],       // 可选：多 bbox（题干/作答分离时）
  "reason": "计算步骤错误：第2步中3×4应为12而非13",
  "standard_answer": "正确答案：45",
  "question_number": "27",  // 题号（字符串，例：\"27\" / \"28(1)②\"）
  "knowledge_tags": ["数学", "几何", "三角形"],
  "cross_subject_flag": false,
  "math_steps": [
    {
      "index": 1,
      "verdict": "correct",
      "expected": "3×4=12",
      "observed": "3×4=12"
    },
    {
      "index": 2,
      "verdict": "incorrect",
      "expected": "12+5=17",
      "observed": "13+5=18",
      "hint": "请重新检查第1步的计算结果",
      "severity": "calculation"
    }
  ],
  "geometry_check": {
    "description": "辅助线BE画对了；∠ABC标注缺失",
    "elements": [
      {"type": "line", "label": "BE", "status": "correct"},
      {"type": "angle", "label": "ABC", "status": "missing"}
    ]
  },
  "semantic_score": 0.92,  // 英语主观题
  "similarity_mode": "strict",
  "keywords_used": ["photosynthesis", "chlorophyll"]
}
```

---

## 3. 作业批改接口 (Grade API)

### 3.1 POST /grade
**描述**: 批改作业图片，支持数学和英语

#### 请求头
```http
POST /grade HTTP/1.1
Content-Type: application/json
X-Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
X-Request-Id: req-123456
```

#### 请求体 (GradeRequest)
```json
{
  "images": [
    {"url": "https://cdn.example.com/homework1.jpg"},
    {"base64": "data:image/jpeg;base64,/9j/4AAQ..."}
  ],
  "upload_id": "upl_xxx",
  "subject": "math",
  "batch_id": "batch-20250106-001",
  "session_id": "sess-abc123",
  "mode": "strict"
}
```

**字段说明**:
- `upload_id` (可选): `POST /uploads` 返回的 id（=submission_id）。当提供 `upload_id` 且 `images` 为空/省略时，后端会从 `submissions.page_image_urls` 反查图片列表。
- `images` (必需\*): 1-4 张图片，每项为 `ImageRef`（url 或 base64 二选一），支持 jpg/png/webp；\*当 `upload_id` 已提供并可反查时可省略/为空。
- 上传要求：单文件不超过 5 MB（可通过 `MAX_UPLOAD_IMAGE_BYTES` 配置）；**强烈推荐公网 URL**（禁止 127/localhost/内网）；若使用 `base64`，必须是 **Data URL**（`data:image/...;base64,...`），且超限直接 400。为减少无效调用，建议入口预检 URL/大小/格式，不合规直接返回 400。
- `subject` (必需): "math" | "english"
- `batch_id` (可选): 客户端批次标识，用于日志追踪
- `session_id` (推荐): 会话/批次 ID，24h 生命周期，便于上下文续接
- `mode` (可选): "normal"(~0.85) | "strict"(~0.91，自动提炼关键术语)，默认 "normal"
- 幂等键使用 Header `X-Idempotency-Key`，Body 不支持。
- `vision_provider` (可选): 用户可选视觉模型，限定值 `"doubao"`(Ark doubao-seed-1-6-vision-250815) | `"qwen3"`(SiliconFlow Qwen/Qwen3-VL-32B-Thinking)；未指定默认 `"doubao"`。不对外提供 OpenAI 视觉选项。

#### 响应体 (GradeResponse) - 同步模式
```json
{
  "wrong_items": [/* WrongItem数组 */],
  "summary": "本次批改共检测到5道题，发现2处错误。错误主要集中在计算步骤的准确性。",
  "subject": "math",
  "job_id": null,  // 同步模式为null
  "status": "done",
  "total_items": 5,
  "wrong_count": 2,
  "cross_subject_flag": false,
  "warnings": ["第3题疑似英文表述，但按数学批改"]
}
```

#### 响应体 (GradeResponse) - 异步模式
```json
{
  "wrong_items": [],
  "summary": "任务已创建，正在后台处理",
  "subject": "math",
  "job_id": "job-789xyz",
  "status": "processing",
  "total_items": null,
  "wrong_count": null,
  "cross_subject_flag": null,
  "warnings": []
}
```

**处理规则**:
- 服务按耗时自动判断同步/异步：
  - 轻量/短任务优先同步返回（期望 < 60s）。
  - 预估超时或大批量则进入异步队列，返回 202 + `job_id`。
- 通过 GET `/jobs/{job_id}` 查询异步状态；回调模式可选（见需求 4.1）。

### 3.2 GET /jobs/{job_id}
**描述**: 查询异步批改任务状态

#### 响应体
```json
{
  "job_id": "job-789xyz",
  "status": "done",  // queued | processing | running | done | failed
  "result": {
    "wrong_items": [/* 完整结果 */],
    "summary": "...",
    "subject": "math",
    "total_items": 5,
    "wrong_count": 2,
    "cross_subject_flag": false,
    "warnings": ["第3题疑似英文表述，但按数学批改"]
  },
  "error": null,
  "created_at": "2025-01-06T10:30:00Z",
  "updated_at": "2025-01-06T10:30:45Z",
  "total_pages": null,
  "done_pages": null,
  "page_summaries": null,
  "question_cards": null
}
```

**补充（多页逐页可用，方案 A）**：
- 当 submission 为多页/多图时，服务端允许在 `status=running` 期间返回“已完成页”的最小摘要，用于前端逐页展示（不必等全量结束）。
- 这些字段是 **可选** 的：单页任务可能为 `null` 或缺失；多页任务也可能在早期尚未填充。
- 另一个可选增强：`question_cards`（三层渐进披露：占位→判定→复核），用于前端“秒级刷出占位卡 + 平滑翻转为结果卡”。

#### 示例：running（多页 partial）
```json
{
  "job_id": "job-789xyz",
  "status": "running",
  "result": null,
  "error": null,
  "created_at": "2025-01-06T10:30:00Z",
  "updated_at": "2025-01-06T10:30:12Z",
  "total_pages": 3,
  "done_pages": 1,
  "page_summaries": [
    {"page_index": 0, "wrong_count": 3, "uncertain_count": 1, "blank_count": 1, "needs_review": true}
  ],
  "question_cards": [
    {
      "item_id": "p1:q:1",
      "question_number": "1",
      "page_index": 0,
      "answer_state": "has_answer",
      "question_content": "两条平行线被…"
    }
  ]
}
```

说明：
- `page_index` 为 0-based（第 1 页为 0）；UI 展示时请用 `page_index + 1`。
- 服务端可能额外返回 `wrong_item_ids`（用于 Demo “进入辅导（本页）”快速绑定），前端不应依赖其稳定存在。
- `question_cards` 的最小字段建议：`item_id, question_number, page_index, answer_state, question_content(可选)`；更多字段（verdict/reason/needs_review）可在后续逐层补全。
- `question_cards` 可选增强（Layer 3 复核卡）：
  - `card_state`: `placeholder|verdict_ready|review_pending|review_ready|review_failed`
  - `review_reasons`: string[]（触发原因，如 `verdict_uncertain/visual_risk:*`）
  - `review_summary`: string（复核提取到的结构化事实摘要，供 UI 展示/辅导引用）
  - `vfe_gate/vfe_scene_type/vfe_image_source/vfe_image_urls`：复核审计信息（可选）

---

## 4. 辅导对话接口 (Chat API)

### 4.1 POST /chat
**描述**: 苏格拉底式辅导对话，支持SSE流式响应

#### 请求头
```http
POST /chat HTTP/1.1
Content-Type: application/json
Accept: text/event-stream
X-Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
Cache-Control: no-cache
```

#### 请求体 (ChatRequest)
```json
{
  "history": [
    {
      "role": "system",
      "content": "你是一位数学辅导老师..."
    },
    {
      "role": "user",
      "content": "第2题我不会"
    },
    {
      "role": "assistant",
      "content": "我们先看看题目要求..."
    }
  ],
  "question": "为什么辅助线要这样画？",
  "subject": "math",
  "session_id": "sess-abc123",
  "submission_id": "upl_xxx",
  "mode": "strict",
  "context_item_ids": [1, "item-abc"]
}
```

**字段说明**:
- `history` (必需): 本次会话的历史消息，最多20条
- `question` (必需): 当前问题
- `subject` (必需): "math" | "english"
- `session_id` (可选): 对应的作业批次会话ID（24h TTL）。服务端也支持从 Header `Last-Event-Id` 兜底恢复 `session_id`（当客户端未持久化 session_id 时使用；前端已实现 `Last-Event-Id` 断线续接）。
- `submission_id` (可选): 用于“历史错题问老师”的 **Chat Rehydrate**。当 `session_id` 缺失/过期且提供 `submission_id` 时，后端会从 `submissions` 真源快照重建最小 qbank，并创建新的 `session_id`（心跳首包返回）。
- `mode` (可选): "normal" | "strict"（对英语辅导/判分一致）
- `context_item_ids` (可选): 关联的错题项，支持“索引 (int)”或“item_id (string)”两种写法；若缓存有错题则注入详情，无数据或缺失项将在上下文 note 中标记；last-event-id 断线续接会重放最近助手消息。
- 幂等键使用 Header `X-Idempotency-Key`，Body 不支持。

#### 视觉信息策略（重要）
本服务的“chat 是否有视觉”分为三层：
1) **默认（稳定优先，当前实现）**：chat 不会把图片作为多模态输入传给 LLM；只基于 `/grade` 写入的 qbank 快照（题干/作答/judgment_basis/warnings/vision_raw_text 摘要等）进行辅导。
2) **切片辅助（UI 体验）**：当 qindex 切片存在时，SSE 的 `chat` 事件可能携带 `focus_image_urls/focus_image_source`（供前端显示“我参考的图”）。注意：这不代表 LLM 真的“看见了图”，只是 UI 展示。
3) **VFE relook（可选兜底，按需开启）**：当用户明确要求看图/发生图形位置关系争议/题目被标记为 visual_risk 时，可对焦点题目做一次“视觉事实抽取”（VFE），将结构化 `visual_facts` 注入上下文后再继续辅导；若 VFE 失败需 fail-closed（避免“贴图但乱讲”）。

#### qindex/slice TTL（默认值）
- qindex 切片与切片索引属于短期数据，**默认 TTL=24 小时**（由配置 `SLICE_TTL_SECONDS` 控制）；过期后可重新生成。

#### SSE响应格式
```http
HTTP/1.1 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no

event: heartbeat
data: {"timestamp": "2025-01-06T10:31:00Z", "session_id": "sess-abc123"}

event: chat
id: 1
data: {"role": "assistant", "content": "我们来看一下辅助线的作用。", "delta": true, "is_hint": true}

event: chat
id: 2
data: {"role": "assistant", "content": "\\n\\n你能告诉我三角形ABC有什么特点吗？", "delta": false, "is_hint": true}

event: done
data: {"session_id": "sess-abc123", "interaction_count": 2, "status": "continue"}
```

> 心跳间隔建议 30s；若 90s 内无任何数据（含 heartbeat），服务器或反向代理可主动断开，客户端需重连。另：可用 `CHAT_IDLE_DISCONNECT_SECONDS` 配置“LLM 长时间无输出时主动关闭 SSE”（安全兜底，默认关闭；生产建议先取 120s，上线后按 `chat_llm_first_output` 日志的 p99 再回调）。客户端重连时**可选**携带 `Last-Event-Id`（若未保存 `session_id`），服务端会兜底恢复 session 并按时间顺序重放最近最多 3 条 assistant 消息（仅当前 session）。

**SSE事件类型**:
1. `heartbeat`: 心跳事件（默认每 30 秒一次；可用 `CHAT_HEARTBEAT_INTERVAL_SECONDS` 配置），保持连接
   ```json
   {"timestamp": "2025-01-06T10:31:00Z"}
   ```

2. `thinking`: 思考过程，用于显示"AI正在思考"
   ```json
   {"status": "analyzing|generating_hint|consulting_knowledge", "progress": 0-100}
   ```

3. `chat`: 消息片段，支持流式传输
   ```json
   {
     "role": "assistant",
     "content": "部分内容",
     "delta": true,  // 是否为增量内容
     "is_hint": true  // 是否为提示（true）还是直接解析（false）
   }
   ```

4. `done`: 会话结束标记（无硬性轮次上限）
   ```json
   {
     "session_id": "sess-abc123",
     "status": "continue|explained|error"  // 继续对话|模型认为已充分解释|异常结束
   }
   ```
   > 说明：当前服务端不强制轮数封顶；`status` 通常为 `continue`（可继续提问），异常时为 `error`。`explained` 为保留语义位，便于未来扩展。

5. `error`: 错误事件
   ```json
   {
     "code": "SESSION_EXPIRED",
     "message": "会话已超时，请重新开始",
     "retry_after": 30
   }
   ```

#### 非流式 JSON 响应（备用/测试场景）
当客户端不支持 SSE，可使用非流式返回：
```json
{
  "messages": [
    {"role": "assistant", "content": "我们来看一下辅助线的作用。"},
    {"role": "assistant", "content": "你能告诉我三角形ABC有什么特点吗？"}
  ],
  "session_id": "sess-abc123",
  "retry_after_ms": null,
  "cross_subject_flag": false
}
```

---

## 5. 错题本接口（Mistakes API，Phase 2）

> 目的：支持“历史错题页 / 排除-恢复 / 基础统计（知识点薄弱）”。  
> 数据来源：以 `submissions.grade_result.wrong_items` 作为 durable snapshot；`mistake_exclusions` 只影响统计/报告，不改历史事实。

### 5.1 GET /mistakes
**描述**：按用户聚合历史错题（跨 submission）。

**Query**：
- `limit_submissions`：默认 20，最大 50（按 submission 分页）
- `before_created_at`：可选，ISO 时间字符串；用于向前翻页（取 `< before_created_at`）
- `include_excluded`：默认 false；为 true 时包含被排除的错题

**响应**：
```json
{
  "items": [
    {
      "submission_id": "upl_xxx",
      "session_id": "sess_xxx",
      "subject": "math",
      "created_at": "2025-12-29T10:00:00Z",
      "item_id": "item-1",
      "question_number": "2",
      "reason": "计算错误…",
      "severity": "calculation",
      "knowledge_tags": ["数学", "代数"],
      "raw": {}
    }
  ],
  "next_before_created_at": "2025-12-28T10:00:00Z"
}
```

### 5.2 GET /mistakes/stats
**描述**：基础统计（当前仅按 `knowledge_tags` 聚合）。

**响应**：
```json
{
  "next_before_created_at": "2025-12-28T10:00:00Z",
  "knowledge_tag_counts": [
    {"tag": "代数", "count": 12},
    {"tag": "几何", "count": 8}
  ]
}
```

### 5.3 POST /mistakes/exclusions
**描述**：排除错题（只影响统计/报告，不改历史事实）。

**请求**：
```json
{
  "submission_id": "upl_xxx",
  "item_id": "item-1",
  "reason": "误判"
}
```

**响应**：
```json
{"ok": true}
```

### 5.4 DELETE /mistakes/exclusions/{submission_id}/{item_id}
**描述**：恢复错题（撤销排除）。

**响应**：
```json
{"ok": true}
```

---

## 6. 学习报告接口（Reports API，Phase 2）

> 目的：生成可审计、可追溯的学情分析报告（先 Features Layer，后续再接 Narrative Layer）。  
> 数据来源：`question_attempts`（含正确题，提供分母）+ `question_steps`（过程诊断）+ `mistake_exclusions`（排除语义）。

### 6.1 GET /reports/eligibility
**描述**：报告解锁条件查询（前端 Report Tab gating）。

> 说明：严禁用 `/mistakes` 推断 submission 数（全对 submission 会被漏掉）。该接口以 `submissions` 为权威数据源。

**查询参数**：
- `mode`：`demo|periodic`（默认 `demo`）
  - `demo`：默认门槛 `required_count=3`、`required_days=0`
  - `periodic`：默认门槛 `required_count=3`、`required_days=3`（同科目 distinct days）
- `subject`：可选（`math|english`），用于“同科目门槛”统计
- `min_submissions`：可选（默认随 mode），最小 submission 数
- `min_distinct_days`：可选（默认随 mode），最小 distinct days
- `window_days`：可选（默认 90），统计窗口

**响应（200）**：
```json
{
  "eligible": false,
  "submission_count": 2,
  "required_count": 3,
  "distinct_days": 1,
  "required_days": 3,
  "subject": "math",
  "reason": "need_more_submissions",
  "progress_percent": 66,
  "sample_submission_ids": ["upl_xxx", "upl_yyy"]
}
```

### 6.2 POST /reports
**描述**：创建异步报告生成任务，返回 `job_id`。

**请求**：
```json
{
  "window_days": 7,
  "subject": "math",
  "submission_id": null
}
```

说明：
- `submission_id` 可选：用于 Demo/联调的“单次作业报告”模式；当传入时，worker 会忽略 `window_days`，仅针对该 submission 生成报告。

**响应（202）**：
```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

### 6.3 GET /reports/jobs/{job_id}
**描述**：查询报告任务状态（queued/pending/running/done/failed）。

**响应**：直接返回 `report_jobs` 行（字段可能随实现演进，以 `status/report_id/error` 为主）。

### 6.4 GET /reports/{report_id}
**描述**：获取报告内容（Features Layer 为主）。

**响应**：直接返回 `reports` 行（重点字段：`stats`/`content`/`title`/`params`）。

其中 `stats`（Features Layer）字段约定（只增不删，前端不二次计数）：
- `overall`：总体分母与正确/错误/不确定统计（含 `sample_size`）
- `knowledge_mastery.rows[]`：知识点掌握度（每个 tag 的 sample_size/accuracy/error_rate）
- `type_difficulty.rows[]`：题型×难度矩阵（用于薄弱点热力/列表）
- `cause_distribution`：题目级错因分布（基于 `question_attempts.severity`）
- `coverage`：标签/错因/steps 覆盖率提示（用于 UI 防误导）
- `trends`：趋势序列（Top5 知识点曲线 + Top3 错因曲线；按 submission 或 3 天游标分桶）
- `meta.cause_definitions`：错因解释字典（用于 UI “!” tooltip）

`trends` 口径（WS‑C C‑7）：
- `granularity = submission | bucket_3d`
- `points[]`：时间升序；每个点包含 `knowledge_top5`（tag→wrong_count）与 `cause_top3`（severity→wrong_count）
- wrong_count 定义：`verdict in {'incorrect','uncertain'}` 的题目数

示例（截断）：
```json
{
  "stats": {
    "features_version": "features_v2",
    "overall": {"sample_size": 30, "accuracy": 0.73, "error_rate": 0.27},
    "cause_distribution": {
      "severity_counts": {"calculation": 10, "concept": 3, "unknown": 17},
      "severity_rates": {"calculation": 0.33, "concept": 0.10, "unknown": 0.57}
    },
    "coverage": {"tag_coverage_rate": 0.9, "severity_coverage_rate": 0.95, "steps_coverage_rate": 0.2},
    "trends": {
      "granularity": "bucket_3d",
      "selected_knowledge_tags": ["勾股定理", "一次函数", "相似三角形"],
      "selected_causes": ["calculation", "concept", "format"],
      "points": [
        {"point_key": "2026-01-01~2026-01-03", "knowledge_top5": {"勾股定理": 3}, "cause_top3": {"calculation": 2}}
      ]
    },
    "meta": {"cause_definitions_version": "cause_v0", "cause_definitions": {"calculation": {"display_name_cn": "计算错误"}}}
  }
}
```

### 6.5 GET /reports
**描述**：列出历史报告（按 `created_at desc`）。

**响应**：
```json
{"items": []}
```

### 6.6 GET /submissions
**描述**：作业历史列表（用于 Home Recent Activity / History List；不能用 `/mistakes` 推断，否则全对作业会漏）。

**查询参数**：
- `subject`：可选（`math|english`）
- `limit`：可选（默认 20，最大 100）
- `before`：可选（ISO timestamp；返回 `created_at < before` 的更早记录，用于分页）

**响应（200）**：
```json
{
  "items": [
    {
      "submission_id": "upl_xxx",
      "created_at": "2026-01-03T14:48:43Z",
      "subject": "math",
      "total_pages": 3,
      "done_pages": 3,
      "session_id": "session_xxx",
      "summary": {
        "total_items": 18,
        "wrong_count": 2,
        "uncertain_count": 1,
        "blank_count": 0,
        "score_text": "95/100"
      }
    }
  ],
  "next_before": "2026-01-02T00:00:00Z"
}
```

### 6.7 GET /submissions/{submission_id}
**描述**：作业历史详情（方案B：读取 submission 快照直接渲染，不重建 job）。

**响应（200）**：
```json
{
  "submission_id": "upl_xxx",
  "created_at": "2026-01-03T14:48:43Z",
  "subject": "math",
  "total_pages": 3,
  "done_pages": 3,
  "session_id": "session_xxx",
  "page_image_urls": ["https://..."],
  "vision_raw_text": "（可选）",
  "page_summaries": [
    {"page_index": 0, "wrong_count": 2, "uncertain_count": 1, "blank_count": 0, "needs_review": true}
  ],
  "question_cards": [
    {
      "item_id": "p1:q:1",
      "question_number": "1",
      "page_index": 0,
      "answer_state": "has_answer",
      "question_content": "两条平行线被…",
      "card_state": "verdict_ready",
      "verdict": "incorrect",
      "reason": "…",
      "needs_review": true
    }
  ],
  "questions": [
    {
      "item_id": "p1:q:1",
      "question_number": "1",
      "question_content": "（完整题干文本）",
      "student_answer": "（可选）",
      "answer_status": "（可选）",
      "answer_state": "has_answer",
      "verdict": "incorrect",
      "reason": "…"
    }
  ]
}
```

### 6.8 POST /submissions/{submission_id}/questions/{question_id}
**描述**：用户手工纠正单题判定（verdict），用于“待定题/错题/对题”人工确认；后端会重算 submission 的聚合统计并同步 `grade_result.wrong_items`。

**请求体**：
```json
{"verdict": "correct"}
```

**响应（200）**：
```json
{
  "success": true,
  "submission_id": "upl_xxx",
  "question_id": "p1:q:1",
  "verdict": "correct",
  "summary": {
    "total_items": 18,
    "wrong_count": 2,
    "uncertain_count": 1,
    "blank_count": 0
  }
}
```

---

## 7. 错误处理 (Error Handling)

### 7.1 HTTP状态码

| 状态码 | 说明 | 场景 |
|--------|------|------|
| 200 | OK | 成功响应 |
| 202 | Accepted | 异步任务创建成功 |
| 400 | Bad Request | 参数错误、字段缺失 |
| 401 | Unauthorized | 未认证 |
| 403 | Forbidden | 权限不足 |
| 404 | Not Found | 任务不存在 |
| 408 | Request Timeout | 请求超时（>60s） |
| 409 | Conflict | 幂等键冲突 |
| 410 | Gone | 会话过期 |
| 413 | Payload Too Large | 图片过多/过大 |
| 415 | Unsupported Media Type | 非图片格式 |
| 422 | Unprocessable Entity | OCR识别失败 |
| 429 | Too Many Requests | 频率限制 |
| 500 | Internal Server Error | 内部错误 |
| 503 | Service Unavailable | 服务不可用 |

### 7.2 错误响应格式
```json
{
  "error": {
    "code": "INVALID_SUBJECT",
    "message": "不支持的学科类型",
    "details": {
      "received": "physics",
      "supported": ["math", "english"]
    },
    "request_id": "req-123456"
  }
}
```

### 7.3 错误码详细说明

#### 认证相关 (4xx)
- `UNAUTHORIZED` (401): 缺少或无效的认证令牌
- `FORBIDDEN` (403): 无权限访问

#### 请求参数 (4xx)
- `INVALID_SUBJECT` (400): 不支持的subject字段
- `INVALID_BBOX` (422): 坐标格式错误
- `IMAGE_REQUIRED` (400): 缺少图片数据
- `TOO_MANY_IMAGES` (413): 图片数量超过限制（20张）
- `IMAGE_TOO_LARGE` (413): 单张图片过大（>10MB）
- `INVALID_IMAGE_FORMAT` (415): 图片格式不支持（支持jpg/png/webp）

#### 会话相关 (4xx)
- `SESSION_EXPIRED` (410): 会话超过24小时
- `INVALID_SESSION_ID` (404): 会话ID不存在
- `SESSION_LIMIT_EXCEEDED` (429): 会话次数超限

#### 幂等性 (4xx)
- `DUPLICATE_REQUEST` (409): 幂等键已存在
- `IDEMPOTENCY_MISMATCH` (409): 幂等键与请求参数不匹配

#### 处理相关 (5xx)
- `OCR_FAILED` (422): 图像识别失败（模糊/非文字内容）
- `GRADING_TIMEOUT` (408): 批改超时
- `AI_SERVICE_ERROR` (500): LLM服务异常
- `INTERNAL_ERROR` (500): 未分类的内部错误
- `SERVICE_OVERLOADED` (503): 服务过载

---

## 6. 幂等性与重试策略 (Idempotency & Retry)

### 6.1 幂等性机制
- **幂等键**: 使用`X-Idempotency-Key`请求头（建议UUID v4），请求体不接受幂等字段
- **生命周期**: 24小时
- **存储**: Agent服务内存缓存（Redis生产环境）
- **冲突处理**:
  - 键不存在 → 创建新任务
  - 键存在且参数相同 → 返回原结果
  - 键存在但参数不同 → 返回409 Conflict

### 6.2 重试策略

#### 客户端重试 (指数退避)
```
第1次重试: 等待 1秒
第2次重试: 等待 2秒
第3次重试: 等待 4秒
第4次重试: 等待 8秒
最大重试: 5次 (总等待时间: 31秒)
```

#### 服务器端重试
- **AI服务调用**: 自动重试3次（指数退避：1s → 2s → 4s）
- **OCR服务**: 失败后不重试，返回422错误
- **Webhook回调**: 失败后自动重试3次（最多5次），指数退避

### 6.3 超时策略

| 接口 | 超时时间 | 说明 |
|------|----------|------|
| POST /grade | 60s | 包含AI处理时间 |
| POST /chat | 60s | SSE流式传输 |
| GET /jobs | 10s | 查询任务状态 |
| SSE心跳 | 90s | 无数据自动断开 |

---

## 7. 限流与配额 (Rate Limiting)

### 7.1 限流规则

#### 按用户
- **批改**: 100次/小时，10次/分钟
- **聊天**: 200次/小时，20次/分钟
- **并发**: 最多5个活跃会话

#### 按IP
- **无认证**: 50次/小时，5次/分钟
- **有认证**: 200次/小时

### 7.2 限流响应头
```http
HTTP/1.1 429 Too Many Requests
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1704528000
Retry-After: 60
```

### 7.3 配额超限
```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "请求频率超限",
    "details": {
      "limit": 10,
      "window": "1m",
      "reset_at": "2025-01-06T10:32:00Z"
    }
  }
}
```

---

## 8. 监控与可观测性 (Monitoring)

### 8.1 日志规范
所有日志包含以下字段：
- `request_id`: 请求唯一标识
- `session_id`: 会话ID
- `user_id`: 用户ID（如果认证）
- `latency_ms`: 处理耗时（毫秒）
- `model`: 使用的AI模型（如 "gpt-4o"）

### 8.2 追踪头
```http
X-Request-Id: req-123456
X-Session-Id: sess-abc123
X-Batch-Id: batch-20250106-001
```

### 8.3 性能指标
- **P50响应时间**: <500ms
- **P95响应时间**: <2000ms
- **P99响应时间**: <5000ms
- **错误率**: <1%
- **可用性**: ≥99.9%

---

## 9. 版本管理 (Versioning)

### 9.1 版本策略
- **URI版本**: `/api/v1/grade`, `/api/v1/chat`
- **弃用通知**: 提前90天通知
- **兼容期**: 旧版本保留6个月

### 9.2 版本迁移示例
```http
# v1.x
POST /api/v1/grade

# 未来 v2.x
POST /v2/grade  // 新增字段或行为改变
```

---

## 10. 安全规范 (Security)

### 10.1 传输安全
- **生产环境**: 强制HTTPS，TLS 1.2+
- **证书**: 使用Let's Encrypt或企业CA

### 10.2 数据保护
- **短期数据**: qindex 切片/切片索引默认 24 小时 TTL（`SLICE_TTL_SECONDS`）
- **长期数据**: 原始图片/批改结果/识别原文的生命周期由上层“用户与数据管理”策略决定（本服务仅 best-effort 写入并回查）
- **日志**: 不记录完整图片内容
- **缓存**: 加密存储

### 10.3 CORS配置
```javascript
const corsOptions = {
  origin: ['https://app.example.com'],
  credentials: true,
  methods: ['GET', 'POST', 'OPTIONS']
}
```

---

## 认证与配额 (Auth & Quota)

### 认证模式
- **AUTH_MODE=dev**：默认使用 `X-User-Id`/`DEV_USER_ID` 作为用户标识（仅开发/测试）。
- **AUTH_MODE=local**：手机号验证码登录 + 本地 JWT（Bearer）。
- **AUTH_MODE=supabase**：Bearer 走 Supabase Auth 令牌（/auth/v1/user 校验）。
- 当 `AUTH_REQUIRED=1` 时，所有业务接口必须携带 Bearer token，否则 401。

### POST /api/v1/auth/sms/send
发送短信验证码（当前默认 `SMS_PROVIDER=mock`）。

**请求体**
```json
{ "phone": "13800138000" }
```

**响应体**
```json
{ "ok": true, "expires_in_seconds": 300, "code": "123456" }
```
> `code` 仅在非生产环境且 `SMS_RETURN_CODE_IN_RESPONSE=1` 时返回。

### POST /api/v1/auth/sms/verify
验证验证码并签发 JWT。

**请求体**
```json
{ "phone": "13800138000", "code": "123456" }
```

**响应体**
```json
{
  "access_token": "jwt...",
  "token_type": "bearer",
  "expires_at": "2025-01-06T10:30:00Z",
  "user": { "user_id": "usr_xxx", "phone": "+8613800138000" }
}
```

### GET /api/v1/me/quota
查询当前用户剩余 CP/报告券（CP 由 BT 折算，BT 按用量精确扣除）。

**响应体**
```json
{
  "cp_left": 120,
  "report_coupons_left": 1,
  "trial_expires_at": "2025-01-10T00:00:00Z",
  "plan_tier": "S1",
  "data_retention_tier": "3m"
}
```

---

## 家庭-子女（Profile）账户切换（Implemented）

> 说明：本节已落地。所有业务数据读写已按 `(user_id, profile_id)` 隔离。

### 约束与计费
- **配额/计费归属**：归属家长主账号 `user_id`（家庭共用），不按 `profile_id` 计费。
- **数据隔离维度**：除认证外，所有业务数据读写都应按 `(user_id, profile_id)` 隔离。

### Header：X-Profile-Id

客户端（支持 Profile 的版本）应在所有业务请求头携带：
```http
X-Profile-Id: <profile_id>
```

后端解析规则（兼容旧客户端，避免阻断）：
- 若提供 `X-Profile-Id`：必须属于当前 `user_id`，否则 403。
- 若未提供：自动使用该 `user_id` 的默认 profile（若不存在则自动创建一个默认 profile）。

### Profiles API（建议）

#### GET /api/v1/me/profiles
返回当前用户所有子女档案与默认 profile。

**响应体**
```json
{
  "default_profile_id": "prf_123",
  "profiles": [
    {
      "profile_id": "prf_123",
      "display_name": "大儿子",
      "avatar_url": null,
      "is_default": true,
      "created_at": "2026-01-17T01:23:45Z"
    }
  ]
}
```

#### POST /api/v1/me/profiles
创建子女档案（同一 `user_id` 下 `display_name` 必须唯一）。

**请求体**
```json
{ "display_name": "小女儿", "avatar_url": null }
```

#### PATCH /api/v1/me/profiles/{profile_id}
更新子女档案（重命名/头像等）。

#### POST /api/v1/me/profiles/{profile_id}/set_default
设置默认 profile（前端切换时可调用，便于“无 header 兼容时”也能落到正确 profile）。

#### DELETE /api/v1/me/profiles/{profile_id}
删除 profile（限制：不能删除最后一个；删除默认时需自动迁移默认到另一个 profile）。

### 传错账户补救（建议）

#### POST /api/v1/submissions/{submission_id}/move_profile
把一次作业（submission）及其派生事实迁移到另一个 profile（仅限同一 user）。

**请求体**
```json
{ "to_profile_id": "prf_456" }
```

**响应体**
```json
{ "ok": true }
```

### 管理员接口（WS-G，最小可用）
所有管理员接口需 `X-Admin-Token`。

#### GET /api/v1/admin/users?phone=...&limit=...&include_wallet=...
#### GET /api/v1/admin/users/{user_id}
#### POST /api/v1/admin/users/{user_id}/wallet_adjust
```json
{
  "bt_trial_delta": 0,
  "bt_subscription_delta": 124000,
  "bt_report_reserve_delta": 0,
  "report_coupons_delta": 1,
  "plan_tier": "S2",
  "data_retention_tier": "12m",
  "trial_expires_at": null,
  "reason": "manual grant"
}
```
#### GET /api/v1/admin/audit_logs?limit=...

#### GET /api/v1/admin/usage_ledger?user_id=...&limit=...&before=...
返回该用户的扣费流水（按 `created_at desc`）。

#### GET /api/v1/admin/submissions?user_id=...&profile_id=...&limit=...&before=...
返回该用户的作业列表（可选按 `profile_id` 过滤）。

#### GET /api/v1/admin/reports?user_id=...&profile_id=...&limit=...&before=...
返回该用户的报告列表（可选按 `profile_id` 过滤）。

### 订阅与支付（Subscriptions API）

#### POST /api/v1/subscriptions/orders
创建订阅订单。

**请求体**
```json
{
  "plan_tier": "S1",
  "billing_cycle": "monthly",
  "multiplier": 1
}
```

**响应体**
```json
{
  "order_id": "uuid...",
  "order_no": "ord_...",
  "amount": 19.9,
  "pay_url": "https://..."
}
```

#### POST /api/v1/subscriptions/orders/{order_id}/mock_pay
(Dev Only) 模拟支付成功并自动发货。

### 兑换与核销 (Redemption API)

#### POST /api/v1/subscriptions/redeem
使用兑换码（卡密）激活权益。

**请求体**
```json
{ "code": "ABCD-1234-EFGH" }
```

**响应体**
```json
{
  "ok": true,
  "granted_bt": 12400,
  "granted_coupons": 1
}
```

#### GET /api/v1/subscriptions/redemptions
查询当前用户的兑换历史。

**响应体**
```json
{
  "items": [
    {
      "id": "rdm_...",
      "code": "ABCD-...",
      "card_type": "trial_pack",
      "redeemed_at": "2026-01-20T10:00:00Z"
    }
  ]
}
```

### 用户反馈 (Feedback / Hidden Chat API)

#### POST /api/v1/feedback
发送反馈消息（或聊天消息）。

**请求体**
```json
{ "content": "为什么我的余额不对？", "images": [] }
```

#### GET /api/v1/feedback
获取反馈对话记录。

**响应体**
```json
{
  "messages": [
    {
      "id": "msg_1",
      "sender": "user",
      "content": "求助...",
      "created_at": "..."
    },
    {
      "id": "msg_2",
      "sender": "admin",
      "content": "您好...",
      "created_at": "..."
    }
  ]
}
```

#### GET /api/v1/feedback/check_unread
检查是否有管理员回复（用于红点）。

**响应体**
```json
{ "has_unread": true }
```

---

## 11. 补充接口（Additional Endpoints）

本章节记录已实现但在上述章节中未详细说明的 API 端点。

### 11.1 管理员统计看板（Admin Dashboard）

#### GET /api/v1/admin/stats/dashboard
**描述**：获取业务核心 KPI 统计数据

**请求头**：
```http
GET /api/v1/admin/stats/dashboard HTTP/1.1
X-Admin-Token: <admin_token>
```

**响应体**：
```json
{
  "kpi": {
    "total_users": 1250,
    "paid_ratio": "15.2%",
    "dau": 342,
    "mrr": "¥12,450"
  },
  "cost": {
    "tokens_today": 2450000,
    "subs_today": 128,
    "avg_cost": "0.08"
  },
  "conversion": {
    "trial_conversion": "8.5%",
    "card_redemption_rate": "92.3%"
  },
  "health": {
    "error_rate": "1.2%",
    "latency_p50": "1.8s"
  }
}
```

### 11.2 卡密批次管理（Redeem Card Batches）

#### GET /api/v1/admin/redeem_cards/batches
**描述**：获取卡密批次统计列表

**请求头**：
```http
GET /api/v1/admin/redeem_cards/batches HTTP/1.1
X-Admin-Token: <admin_token>
```

**响应体**：
```json
{
  "items": [
    {
      "batch_id": "BATCH_20260122",
      "created_at": "2026-01-22T10:00:00Z",
      "total_count": 100,
      "active_count": 75,
      "redeemed_count": 20,
      "expired_count": 5
    }
  ]
}
```

#### POST /api/v1/admin/redeem_cards/batches/{batch_id}/disable
**描述**：作废指定批次的所有未兑换卡密

**请求头**：
```http
POST /api/v1/admin/redeem_cards/batches/BATCH_20260122/disable HTTP/1.1
X-Admin-Token: <admin_token>
```

**响应体**：
```json
{
  "ok": true,
  "disabled_count": 75
}
```

#### POST /api/v1/admin/redeem_cards/bulk_update
**描述**：批量更新卡密状态

**请求体**：
```json
{
  "codes": ["ABCD-1234", "EFGH-5678"],
  "status": "disabled"
}
```

**响应体**：
```json
{
  "ok": true,
  "updated_count": 2
}
```

### 11.3 管理员反馈管理（Admin Feedback）

#### GET /api/v1/admin/feedback/users
**描述**：获取有反馈消息的用户列表

**请求头**：
```http
GET /api/v1/admin/feedback/users?limit=20&only_unread=true HTTP/1.1
X-Admin-Token: <admin_token>
```

**查询参数**：
- `limit`：可选，默认 20，最大 100
- `only_unread`：可选，只返回有未读消息的用户

**响应体**：
```json
{
  "items": [
    {
      "user_id": "usr_abc123",
      "unread_count": 2,
      "last_message": "为什么我的余额不对？",
      "last_at": "2026-01-22T14:30:00Z"
    }
  ]
}
```

#### GET /api/v1/admin/feedback/{user_id}
**描述**：获取指定用户的反馈消息列表

**请求头**：
```http
GET /api/v1/admin/feedback/usr_abc123 HTTP/1.1
X-Admin-Token: <admin_token>
```

**响应体**：
```json
{
  "messages": [
    {
      "id": "msg_1",
      "sender": "user",
      "content": "为什么我的余额不对？",
      "created_at": "2026-01-22T14:30:00Z"
    },
    {
      "id": "msg_2",
      "sender": "admin",
      "content": "您好，我们正在查询...",
      "created_at": "2026-01-22T14:35:00Z"
    }
  ]
}
```

#### POST /api/v1/admin/feedback/{user_id}
**描述**：向指定用户发送管理员回复

**请求体**：
```json
{
  "content": "您好，经查询您的余额正常..."
}
```

**响应体**：
```json
{
  "id": "msg_3",
  "sender": "admin",
  "content": "您好，经查询您的余额正常...",
  "created_at": "2026-01-22T14:40:00Z"
}
```

### 11.4 其他补充接口

#### POST /api/v1/submissions/{submission_id}/qindex/rebuild
**描述**：重建指定作业的题号索引

**请求头**：
```http
POST /api/v1/submissions/sub_abc123/qindex/rebuild HTTP/1.1
Authorization: Bearer <jwt_token>
```

**响应体**：
```json
{
  "ok": true,
  "job_id": "job_rebuild_xyz",
  "status": "queued"
}
```

#### POST /api/v1/me/password
**描述**：修改用户密码（AUTH_MODE=local 时可用）

**请求体**：
```json
{
  "old_password": "old123",
  "new_password": "new456"
}
```

**响应体**：
```json
{
  "ok": true
}
```

#### POST /api/v1/me/email/bind
**描述**：绑定邮箱地址

**请求体**：
```json
{
  "email": "user@example.com"
}
```

**响应体**：
```json
{
  "ok": true,
  "verification_required": true
}
```

---

## 附录A: 示例调用 (Appendix A - Examples)

### A.1 完整批改流程
```bash
# 1. 创建批改任务
curl -X POST /api/v1/grade \\
  -H "Content-Type: application/json" \\
  -H "X-Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \\
  -d '{
    "images": [{"url": "https://example.com/math1.jpg"}],
    "subject": "math",
    "mode": "strict"
  }'

# 响应 (异步模式)
# HTTP 202
{
  "job_id": "job-789xyz",
  "status": "processing"
}

# 2. 查询任务状态
curl /api/v1/jobs/job-789xyz

# 3. 获取结果
curl /api/v1/jobs/job-789xyz
# 返回完整批改结果
```

### A.2 聊天辅导流程
```javascript
// 注意：/api/v1/chat 是 “POST + SSE响应”，不能用 EventSource 直接连（EventSource 只支持 GET）。
// 推荐用 fetch 读取 ReadableStream，并按 SSE 协议解析 event/data。
const res = await fetch('/api/v1/chat', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-User-Id': 'dev_user',
    // 若需要断线续接且没保存 session_id，可选带上：'Last-Event-Id': 'sess-abc123'
  },
  body: JSON.stringify({
    history: [],
    question: '这道题怎么做？',
    subject: 'math',
    session_id: 'sess-abc123'
  })
});

// res.body 是 ReadableStream<Uint8Array>，逐块读取并按 `\\n\\n` 分割成 SSE block，
// 每个 block 再解析 `event:`/`data:` 行即可。
```

---

## 附录B: 测试用例 (Appendix B - Test Cases)

### B.1 数学批改测试用例
- **步骤错误**: 计算过程第2步出错
- **几何标注**: 辅助线画对但角度漏标
- **答案正确但过程错**: 最终结果对但步骤有误

### B.2 英语批改测试用例
- **语义相似**: 同义词替换（score=0.92）
- **严格模式**: 必须包含关键术语
- **混合内容**: 英语题含简单算式

### B.3 聊天测试用例
- **多轮引导**: 无硬上限的递进提示循环
- **自然终止**: 用户结束或模型认为已解释充分，不以轮数封顶
- **会话续接**: 断线重连恢复上下文

---

## 附录C: 完整 API 端点列表 (Appendix C - Complete API Endpoints)

> 本附录补充主文档未涵盖的所有已实现 API 端点。

---

## C.1 认证接口 (Auth API)

### POST /auth/sms/send
**描述**: 发送短信验证码

#### 请求体
```json
{
  "phone": "13800138000"  // 支持 11位手机号、+86前缀、86前缀
}
```

#### 响应体
```json
{
  "success": true,
  "message": "验证码已发送",
  "expires_in": 300  // 5分钟有效期
}
```

### POST /auth/sms/verify
**描述**: 验证短信验证码并登录

#### 请求体
```json
{
  "phone": "13800138000",
  "code": "123456"
}
```

#### 响应体
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 86400,
  "user_id": "usr_xxx"
}
```

### POST /auth/login/email
**描述**: 邮箱密码登录

#### 请求体
```json
{
  "email": "user@example.com",
  "password": "hashed_password"
}
```

### POST /auth/logout
**描述**: 用户登出

---

## C.2 用户中心接口 (Me API)

### GET /me/quota
**描述**: 获取用户配额信息（BT/CP/报告券）

#### 响应体
```json
{
  "cp_left": 5000,
  "report_coupons_left": 3,
  "trial_expires_at": "2026-02-28T00:00:00Z",
  "plan_tier": "pro"
}
```

### GET /me/profiles
**描述**: 获取子女档案列表

#### 响应体
```json
{
  "profiles": [
    {
      "profile_id": "prof_xxx",
      "display_name": "小明",
      "is_default": true,
      "created_at": "2026-01-01T00:00:00Z"
    }
  ],
  "total": 1
}
```

### POST /me/profiles
**描述**: 创建子女档案

#### 请求体
```json
{
  "display_name": "小红"
}
```

### PATCH /me/profiles/{profile_id}
**描述**: 更新子女档案

### DELETE /me/profiles/{profile_id}
**描述**: 删除子女档案

### POST /me/profiles/{profile_id}/set_default
**描述**: 设置默认档案

### GET /me/account
**描述**: 获取账户信息

### PATCH /me/account
**描述**: 更新账户信息（昵称等）

### POST /me/password
**描述**: 设置/修改密码

### POST /me/email/bind
**描述**: 绑定邮箱

---

## C.3 提交管理接口 (Submissions API)

### GET /submissions
**描述**: 列出历史提交

#### 查询参数
- `profile_id` (可选): 筛选特定子女档案
- `limit`: 分页大小，默认 20
- `offset`: 分页偏移

#### 响应体
```json
{
  "items": [
    {
      "submission_id": "sub_xxx",
      "subject": "math",
      "total_items": 5,
      "wrong_count": 2,
      "created_at": "2026-01-20T10:00:00Z",
      "profile_id": "prof_xxx"
    }
  ],
  "total": 100
}
```

### GET /submissions/{submission_id}
**描述**: 获取提交详情

### POST /submissions/{submission_id}/questions/{question_id}
**描述**: 更新题目判定（人工修正）

#### 请求体
```json
{
  "verdict": "correct",  // correct | incorrect | uncertain
  "reason": "人工复核：实际答案正确"
}
```

### POST /submissions/{submission_id}/qindex/rebuild
**描述**: 重建题目索引

### POST /submissions/{submission_id}/move_profile
**描述**: 移动提交到其他子女档案

#### 请求体
```json
{
  "to_profile_id": "prof_yyy"
}
```

---

## C.4 错题本接口 (Mistakes API)

### GET /mistakes
**描述**: 列出错题

#### 查询参数
- `include_excluded`: 是否包含已排除的错题，默认 false

### GET /mistakes/stats
**描述**: 错题统计

#### 响应体
```json
{
  "total_mistakes": 50,
  "by_subject": {
    "math": 30,
    "english": 20
  },
  "by_severity": {
    "calculation": 25,
    "concept": 15,
    "format": 10
  }
}
```

### POST /mistakes/exclusions
**描述**: 排除错题（不影响历史，仅影响统计）

#### 请求体
```json
{
  "submission_id": "sub_xxx",
  "item_id": "item_yyy",
  "reason": "已掌握"
}
```

### DELETE /mistakes/exclusions/{submission_id}/{item_id}
**描述**: 恢复已排除的错题

---

## C.5 学情报告接口 (Reports API)

### GET /reports/eligibility
**描述**: 检查报告生成资格

#### 响应体
```json
{
  "eligible": true,
  "reason": null,  // 如不满足，说明原因
  "required_submissions": 3,
  "current_submissions": 5
}
```

### POST /reports
**描述**: 创建学情报告（异步）

#### 请求体
```json
{
  "start_date": "2026-01-01",
  "end_date": "2026-01-31",
  "profile_id": "prof_xxx"  // 可选，默认所有子女
}
```

#### 响应体
```json
{
  "job_id": "report_job_xxx",
  "status": "queued"
}
```

### GET /reports/jobs/{job_id}
**描述**: 查询报告任务状态

### GET /reports/{report_id}
**描述**: 获取报告内容

### GET /reports
**描述**: 列出历史报告

---

## C.6 订阅与兑换接口 (Subscriptions API)

### POST /subscriptions/orders
**描述**: 创建订阅订单

#### 请求体
```json
{
  "plan_type": "monthly",  // monthly | yearly
  "payment_method": "alipay"  // alipay | wechat
}
```

### POST /subscriptions/orders/{order_id}/mock_pay
**描述**: Mock 支付（开发环境）

### POST /subscriptions/redeem
**描述**: 兑换码兑换

#### 请求体
```json
{
  "code": "REDEEM-1234-5678"
}
```

#### 响应体
```json
{
  "success": true,
  "bt_granted": 100,
  "message": "兑换成功，获得 100 BT"
}
```

### GET /subscriptions/redemptions
**描述**: 查询兑换历史

---

## C.7 反馈接口 (Feedback API)

### POST /feedback
**描述**: 提交用户反馈

#### 请求体
```json
{
  "content": "批改结果有误...",
  "submission_id": "sub_xxx",  // 可选，关联具体提交
  "item_id": "item_yyy"  // 可选，关联具体题目
}
```

### GET /feedback
**描述**: 获取反馈列表

#### 查询参数
- `limit`: 默认 50

### GET /feedback/check_unread
**描述**: 检查是否有未读的管理员回复

#### 响应体
```json
{
  "has_unread": true,
  "unread_count": 2
}
```

---

## C.8 管理员接口 (Admin API)

> **注意**: 所有管理员接口需要 `X-Admin-Token` 头部认证

### GET /admin/users
**描述**: 列出所有用户

#### 查询参数
- `limit`, `offset`: 分页
- `created_after`, `created_before`: 时间筛选

### GET /admin/users/{user_id}
**描述**: 获取用户详情

### POST /admin/users/{user_id}/wallet_adjust
**描述**: 调整用户钱包（补偿/奖励）

#### 请求体
```json
{
  "bt_delta": 50,  // 正数增加，负数扣除
  "reason": "活动奖励"
}
```

### POST /admin/users/{user_id}/grant
**描述**: 授予订阅或报告券

### GET /admin/audit_logs
**描述**: 审计日志查询

### GET /admin/usage_ledger
**描述**: 使用记录统计

### GET /admin/submissions
**描述**: 查看所有提交

### GET /admin/reports
**描述**: 查看所有报告

### POST /admin/redeem_cards/generate
**描述**: 批量生成兑换码

#### 请求体
```json
{
  "batch_size": 100,
  "bt_value": 50,
  "expires_at": "2026-12-31T23:59:59Z",
  "prefix": "PROMO-"
}
```

### GET /admin/redemptions
**描述**: 查看所有兑换记录

### GET /admin/redeem_cards/batches
**描述**: 查看兑换码批次

### POST /admin/redeem_cards/batches/{batch_id}/disable
**描述**: 禁用整个批次的兑换码

### POST /admin/redeem_cards/bulk_update
**描述**: 批量更新兑换码状态

### GET /admin/stats/dashboard
**描述**: 仪表盘统计数据

#### 响应体
```json
{
  "dau": 1500,
  "mau": 15000,
  "total_gradings_today": 3500,
  "revenue_today": 5000.00
}
```

### GET /admin/feedback/users
**描述**: 查看有反馈的用户列表

### GET /admin/feedback/{user_id}
**描述**: 查看特定用户的反馈

### POST /admin/feedback/{user_id}
**描述**: 回复用户反馈

---

**文档版本**: v1.2.0
**最后更新**: 2026-01-30
**维护人**: Atlas (OpenCode)
**变更说明**: 补充 40+ 缺失端点，移除 BFF 引用
