# API Contract (MVP)

本文件定义本仓库（Python FastAPI Agent 服务）的对外 API 约定，用于对齐前后端与测试脚本。以 `homework_agent/models/schemas.py` 为字段真源；本文件补充“业务语义、行为约束与事件流格式”。

## Base
- Base URL：`/api/v1`
- Headers
  - `X-Idempotency-Key`（可选）：用于 `/grade` 幂等（24h 生命周期；参数不同返回 409）
  - `X-User-Id`（可选，开发态）：用于用户隔离；未提供则后端使用 `DEV_USER_ID`

## 1) Upload (推荐的权威原图路径)

### `POST /api/v1/uploads`
上传原始文件到后端，由后端存储到 Supabase Storage（用户隔离路径），返回 `upload_id` 与可用的 `page_image_urls`。

- Content-Type：`multipart/form-data`
- Form fields：
  - `file`（必填）：图片或 PDF（PDF 仅拆前 8 页）
  - `session_id`（可选）：若传入，可用于把上传与一次批改会话关联（MVP）
- Response（JSON）：
  - `upload_id`: string（一次上传=一次 Submission）
  - `user_id`: string
  - `session_id`: string|null
  - `page_image_urls`: string[]

## 2) Grade

### `POST /api/v1/grade`
对作业图片进行识别与批改（统一阅卷 Agent 单次调用完成“识别 + 理解 + 判题”，输出 `vision_raw_text` 与 `judgment_basis` 作为判定依据）。支持两种输入：
- 直接给 `images[].url`（公网 URL）
- 给 `upload_id`（推荐）：后端按 `X-User-Id/DEV_USER_ID + upload_id` 反查并补齐图片列表

- Request（JSON，简化）：
  - `subject`: `"math" | "english"`
  - `vision_provider`: `"doubao" | "qwen3"`（默认 doubao）
  - `images`: `{url?: string, base64?: string}[]`
  - `upload_id`: string|null（可选；当 `images=[]` 时启用反查）
  - `session_id`: string|null（可选；为空时后端会生成，确保 grade→chat 可交付）
- Response（JSON，简化）：
  - `status`: `"done" | "failed" | "processing"`
  - `session_id`: string（chat 必需）
  - `summary`: string
  - `wrong_items`: array
    - 每个 wrong_item 包含 `judgment_basis?: string[]`（判定依据，中文短句）
  - `questions`: array（全题列表，含正确题目）
    - 每题包含 `verdict` 与 `judgment_basis?: string[]`
  - `warnings`: string[]
  - `vision_raw_text`: string|null
  - `job_id`: string|null（当异步时）
  - 说明：前端默认展示 `judgment_basis` 与 `vision_raw_text`；如视觉信息不足，需在 `warnings` 明确提示。

### `GET /api/v1/jobs/{job_id}`
异步批改任务查询（当 `/grade` 返回 `status="processing"` 时使用）。

## 3) Chat (SSE)

### `POST /api/v1/chat`
报告式对话（直接结论 + 解释），使用 SSE 返回事件流。**前置要求**：必须先完成一次 `/grade` 并拿到 `session_id`（即便全对也允许对话）。

- Request（JSON，简化）：
  - `session_id`: string
  - `subject`: `"math" | "english"`
  - `question`: string（用户问题）
  - `history`: `{role:"user"|"assistant", content:string}[]`（可选）
  - `context_item_ids`: string[]（可选）
- Response：`text/event-stream`
  - `event: heartbeat`：心跳
  - `event: chat`：增量消息（JSON，见 `ChatResponse`）
  - `event: error`：错误（JSON，见 `ErrorPayload`）
  - `event: done`：结束（JSON）

#### ErrorPayload（HTTP JSON / SSE 通用）
- `code`: string（例如 `E4220` / `E5000`）
- `error`: string（主要错误信息，旧客户端只需读这个）
- `message`: string（与 `error` 同义）
- `details`: object|null（可选，结构化附加信息）
- `retry_after_ms`: number|null（可选）
- `request_id`: string|null（可选）
- `session_id`: string|null（可选）

#### 行为约束（产品要求）
- chat 必须基于 `/grade` 交付的 qbank/错题上下文对话；缺失则明确提示用户先批改，禁止编造。
- **chat 不实时看图**：只使用 `/grade` 产出的 `judgment_basis` 与 `vision_raw_text`。
- 若视觉信息不足：仍给出结论，但必须提示“依据不足，可能误读”。

#### ChatResponse（SSE `event: chat`）
除 `messages/session_id/retry_after_ms` 外，SSE 增量消息还会携带 UI 辅助字段：
- `focus_image_urls?: string[]`：当前聚焦题的切片/整页 URL（用于在 chat 气泡中显示“我参考的图”）
- `focus_image_source?: "slice_figure" | "slice_question" | "page" | "unknown"`：URL 来源提示（图形/题干/整页）
- `question_candidates?: string[]`：当题目无法定位时返回的候选题目（用于 UI 渲染快捷按钮/列表）

## 4) Session Debug (仅用于验收/调试)

### `GET /api/v1/session/{session_id}/qbank`
返回该 session 的 qbank 元信息（默认不返回整段 `vision_raw_text`）。

### `GET /api/v1/session/{session_id}/progress`
返回 `/grade` 的 best-effort 进度信息（用于 UI 轮询）。

## 5) Retention (业务语义)
- Submission（原始图片 + 识别原文 + 批改结果）：长期保留（未来支持用户删除；系统静默 180 天清理）
- chat_history：7 天
- qindex slices：7 天
