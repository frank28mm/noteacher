# Homework Agent API Contract

## 1. 概览 (Overview)

本契约定义Node.js BFF与Python AI Agent之间的REST API通信协议，支持同步/异步批改和SSE流式聊天辅导。

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
  "base64": "data:image/jpeg;base64,/9j/4AAQ..."  // 可选，兜底。请去掉 data: 前缀；大图建议改用 URL
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
  "subject": "math",
  "batch_id": "batch-20250106-001",
  "session_id": "sess-abc123",
  "mode": "strict"
}
```

**字段说明**:
- `images` (必需): 1-20 张图片，每项为 `ImageRef`（url 或 base64 二选一），支持 jpg/png/webp
- 上传要求：单文件不超过 20 MB；**强烈推荐公网 URL**（禁止 127/localhost/内网）；**Doubao 仅支持 URL（Base64 报错）**；Qwen3 支持 URL（推荐）或 base64（兜底，去掉 data: 前缀，超限直接 400）。为减少无效调用，建议入口预检 URL/大小/格式，不合规直接返回 400。
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
  "status": "done",  // processing | done | failed
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
  "updated_at": "2025-01-06T10:30:45Z"
}
```

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
  "mode": "strict",
  "context_item_ids": [1, "item-abc"]
}
```

**字段说明**:
- `history` (必需): 本次会话的历史消息，最多20条
- `question` (必需): 当前问题
- `subject` (必需): "math" | "english"
- `session_id` (必需): 对应的作业批次会话ID（24h 生命周期，持久化）
- `mode` (可选): "normal" | "strict"（对英语辅导/判分一致）
- `context_item_ids` (可选): 关联的错题项，支持“索引 (int)”或“item_id (string)”两种写法；若缓存有错题则注入详情，无数据或缺失项将在上下文 note 中标记；last-event-id 断线续接会重放最近助手消息。
- 幂等键使用 Header `X-Idempotency-Key`，Body 不支持。

#### SSE响应格式
```http
HTTP/1.1 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no

event: heartbeat
data: {"timestamp": "2025-01-06T10:31:00Z"}

event: thinking
data: {"status": "analyzing", "progress": 20}

event: thinking
data: {"status": "generating_hint", "progress": 60}

event: chat
id: 1
data: {"role": "assistant", "content": "我们来看一下辅助线的作用。", "delta": true, "is_hint": true}

event: chat
id: 2
data: {"role": "assistant", "content": "\\n\\n你能告诉我三角形ABC有什么特点吗？", "delta": false, "is_hint": true}

event: done
data: {"session_id": "sess-abc123", "interaction_count": 2, "status": "continue"}
```

> 心跳间隔建议 30s；若 90s 内无数据/心跳，服务器可主动断开，客户端需重连。客户端重连时可携带 `Last-Event-Id`，服务端会恢复 session 并按时间顺序重放最近最多 3 条 assistant 消息（仅当前 session）。\n*** End Patch

**SSE事件类型**:
1. `heartbeat`: 心跳事件，每30秒发送一次，保持连接
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

## 5. 错误处理 (Error Handling)

### 5.1 HTTP状态码

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

### 5.2 错误响应格式
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

### 5.3 错误码详细说明

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
- **URI版本**: `/v1/grade`, `/v1/chat`
- **弃用通知**: 提前90天通知
- **兼容期**: 旧版本保留6个月

### 9.2 版本迁移示例
```http
# v1.x
POST /v1/grade

# 未来 v2.x
POST /v2/grade  // 新增字段或行为改变
```

---

## 10. 安全规范 (Security)

### 10.1 传输安全
- **生产环境**: 强制HTTPS，TLS 1.2+
- **证书**: 使用Let's Encrypt或企业CA

### 10.2 数据保护
- **敏感数据**: 作业图片7天后自动删除
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

## 附录A: 示例调用 (Appendix A - Examples)

### A.1 完整批改流程
```bash
# 1. 创建批改任务
curl -X POST /v1/grade \\
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
curl /v1/jobs/job-789xyz

# 3. 获取结果
curl /v1/jobs/job-789xyz
# 返回完整批改结果
```

### A.2 聊天辅导流程
```javascript
// SSE连接
const eventSource = new EventSource('/v1/chat', {
  withCredentials: true
});

// 监听事件
eventSource.addEventListener('chat', (event) => {
  const data = JSON.parse(event.data);
  console.log('新消息:', data.content);
});

// 发送消息
fetch('/v1/chat', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-Idempotency-Key': 'uuid-4'
  },
  body: JSON.stringify({
    "history": [],
    "question": "这道题怎么做？",
    "subject": "math",
    "session_id": "sess-abc123"
  })
});
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

**文档版本**: v1.0.0
**最后更新**: 2025-01-06
**维护人**: [Your Name]
**审核人**: [Partner Name]
