# Homework Agent - 标准作业流程 (SOP)

> Version: 2.0.0
> Last Updated: 2025-01-06
> Status: Active

## 目录
1. [工作流程概览](#1-工作流程概览)
2. [详细作业流程](#2-详细作业流程)
3. [决策树](#3-决策树)
4. [错误处理策略](#4-错误处理策略)
5. [质量保证](#5-质量保证)
6. [安全与隐私](#6-安全与隐私)
7. [性能优化](#7-性能优化)
8. [监控与日志](#8-监控与日志)

---

## 1. 工作流程概览

### 1.0 技术栈与边界

#### 1.0.1 核心架构
- 后端框架：FastAPI 0.100+ (Python 3.10+)；HTTP 直连 LLM/Vision API（OpenAI/Anthropic），不使用 Claude Agent SDK、不依赖 .claude 目录。
- AI 模型（Reasoning/Chat）：Phase 1 `/grade` 与 `/chat` 当 provider=ark 时均使用 `ARK_REASONING_MODEL` 指定的 Doubao 模型（测试环境可指向 `doubao-seed-1-6-vision-250815`）；`ARK_REASONING_MODEL_THINKING` 不作为必需项。Qwen3 推理仅作为内部调试/备用，不对外暴露或新增其他 LLM 选项。保留 OpenAI/Anthropic 作为内部备用，不向终端暴露。
- 视觉模型：用户可选 `"doubao"`(Ark doubao-seed-1-6-vision-250815) 或 `"qwen3"`(SiliconFlow Qwen/Qwen3-VL-32B-Thinking)，默认 `"doubao"`；不对外提供 OpenAI 视觉选项。`doubao` **优先公网 URL**，但支持 Data-URL(base64) 兜底（绕开 provider-side URL 拉取不稳定）；`qwen3` 支持 URL 或 Data-URL(base64)。
- 数据存储：Supabase（Postgres + Storage）作为持久化主存；Redis 作为缓存/队列（会话、qbank/qindex、异步任务协调）。
- 队列：Redis list + 独立 worker（qindex 通过 `BRPOP` 消费队列）。
- 部署：Docker；可选 K8s/云函数。

#### 1.0.2 模块划分（建议）
```
homework_agent/
├── main.py              # FastAPI 入口
├── api/                 # 路由层 (/grade, /chat, /jobs)
├── core/                # 业务逻辑：grader/tutor/ocr/prompts
├── models/              # schemas / database
├── services/            # vision/llm/cache 等客户端
├── utils/               # session/validator
└── tests/               # 测试
```

#### 1.0.3 FastAPI 配置规范
- 应用：`app = FastAPI(title="Homework Agent", version="1.0.0")`，DEBUG 依 ENV。
- CORS：仅白名单域，支持凭证。
- 中间件：请求日志、认证、限流、幂等校验（X-Idempotency-Key）。
- 路由：版本前缀 `/api/v1`；依赖注入认证/缓存/会话；响应模型用 Pydantic。
- 异步：`async def` 端点，外部调用用 aiohttp/httpx；SSE/WebSocket 支持流式。
- 错误处理：全局异常处理器统一格式与状态码。

#### 1.0.4 会话/幂等/异步
- 幂等：`X-Idempotency-Key` 头，24h 生命周期；冲突返回 409。
- 同步/异步：小批量/预估 <60s 尽量同步；预估超时/大批量返回 202+job_id，GET /jobs 查询（或回调）。
- 会话（chat_history）：对话历史保留 7 天（定期清理）；辅导链只读当前 Submission（单次上传）上下文，不读历史画像/历史错题；报告链可读取历史用于长期分析。

#### 1.0.5 存储与坐标
- 坐标统一归一化 `[ymin, xmin, ymax, xmax]`，原点左上。
- bbox/切片为可选增强能力：允许 `bbox=None` / `slice_image_url=None`，但必须在 `warnings` 说明“定位不确定，改用整页”。
- bbox 对象（MVP）：整题区域（题干 + 学生作答）；允许多 bbox 列表（题干/作答分离时）。
- 裁剪策略（MVP）：默认 5% padding；裁剪前 clamp 到 [0,1]；裁剪失败回退为整页。
- 图像/切片存 Supabase Storage：切片 TTL 固定 7 天（可配置）；原始图片 + 识别原文 + 批改结果长期保留（除非用户删除或静默 180 天清理）；对话历史 7 天。

### 1.1 核心流程图

```mermaid
graph TD
    A[接收GradeRequest] --> B{验证输入}
    B -->|失败| C[返回错误]
    B -->|成功| D[预处理/切片(可选)] 
    D --> E[Autonomous Grade Agent: 规划→工具→反思→汇总]
    E --> F{判定完成？}
    F -->|失败| G[返回批改失败/needs_review]
    F -->|成功| H[生成结构化结果]
    H --> I[返回GradeResponse]
    I --> M{需要辅导？}
    M -->|否| N[结束]
    M -->|是| O[启动Chat会话（已批改）]
    O --> P[Chat 页面输出：识别原文 + 判断依据 + 批改结论]
    P --> Q{继续提问？}
    Q -->|是| R[继续对话/解释]
    Q -->|否| S[结束会话]
```

### 1.2 输入/输出标准

| 阶段 | 输入 | 处理 | 输出 |
|------|------|------|------|
| **批改** | GradeRequest(images, subject, mode) | 预处理/切片（可选）→ Autonomous Grade Agent | GradeResponse(wrong_items, summary) |
| **辅导** | ChatRequest(history, question) | 上下文理解 → 引导策略 | ChatResponse(messages) 或 SSE流 |
| **会话** | session_id | 状态管理 | 持久化上下文 |

---

## 2. 详细作业流程

### 2.1 阶段1：输入验证与准备

> 幂等：使用 `X-Idempotency-Key` 头；键存在且参数相同返回原结果，参数不同返回 409。

> 同步/异步：小批量/预估 <60s 尝试同步；预估超时或大批量返回 202+job_id，结果通过 GET /jobs/{job_id} 查询（或回调）。

#### SOP-1.1: GradeRequest验证
**触发**: POST /grade

**检查清单**:
```python
✅ 验证字段完整性:
  - images: 1-20张图片，每张<10MB，支持jpg/png/webp
  - upload_id: 可选（推荐；一次上传=一次 Submission；images 为空时由后端反查补齐）
  - subject: math 或 english
  - mode: normal (默认) 或 strict
  - session_id: 可选；为空时后端生成用于 grade→chat 交付（chat 对话历史保留 7 天）
  - batch_id: 可选
  - header: X-Idempotency-Key（推荐）

✅ 验证图片格式:
  - 检查文件头判断真实格式
  - 拒绝损坏的图片文件
  - 转换异常记录到warnings

✅ 生成作业ID:
  - 如果没有session_id，生成格式: session_{random8}
```

**失败处理**:
- 字段缺失 → 400 Bad Request
- 图片问题 → 422 Unprocessable Entity
- 超过限制 → 413 Payload Too Large
- 幂等冲突 → 409 Conflict

#### SOP-1.2: ChatRequest验证  
**触发**: POST /chat  

**检查清单**:  
```python
✅ 验证字段完整性:
  - history: 最多20条消息，role/content 格式
  - question: 非空字符串
  - subject: math 或 english
  - session_id: 必需，来自已完成批改的批次（即便全对也允许辅导）；对话历史保留 7 天

✅ 会话状态检查:
  - 检查 session_id 是否存在于活跃会话中
  - 验证会话是否超时（>7天；超时不恢复对话，仅允许查看该次批改结果/识别原文）
  - 记录当前交互次数（默认不限轮；如需可在错题上下文场景下设置软性上限）

✅ 上下文关联:
  - 验证 context_item_ids 是否存在于之前的批改结果中
  - 加载错题详情作为辅导上下文（若未提供，视为泛辅导但仍限数学/英语）
  - 仅读取当前批次上下文，不读取历史画像；长期画像仅写入不读取
  - 题号解析需支持“非数字题名”（如“思维与拓展/旋转题”等）：用 qbank 的 `question_aliases` 做模糊匹配；若仍无法定位，返回候选题目列表（用于 UI 按钮快速选择）

✅ 看图策略（稳定优先）:
  - Chat **不实时看图**：只读取 `/grade` 产出的 `judgment_basis + vision_raw_text`。
  - 若视觉信息不足：仍给出结论，但必须提示“依据不足，可能误读”，并在 `judgment_basis` 写明依据来源。
  - 如用户仍要求看图：提示“切片生成中/请稍后或补充清晰局部图”，不在 chat 中发起额外视觉调用。
```

### 2.2 阶段2：图像处理与内容识别

#### SOP-2.1: 预处理与切片（可选）
**工具（可选增强）**: 预处理流水线（qindex cache / VLM locator / OpenCV fallback） + qindex 切片

- **默认策略**：best-effort 预处理与切片；不可用时允许跳过，必须通过 `warnings` 解释降级原因。
- **切片策略**：优先 figure + question 双图；必要时回退整页（并写入风险提示）。

**执行方式（重要）**：
- 题块 bbox + 切片裁剪/上传属于重任务，**不得在 API 主进程内同步执行**。
- `/grade` 完成后仅负责 **enqueue** 一个 qindex 任务到 Redis 队列（默认 `qindex:queue`）。
- 独立 worker `python3 -m homework_agent.workers.qindex_worker` 负责消费队列，生成 bbox/slice 并写回 `qindex:{session_id}`。
- chat 侧会把该题切片 refs 透传为 `focus_image_urls/focus_image_source`（用于 UI 渲染）。
- 当题目无法定位时，SSE 会返回 `question_candidates`（候选题目列表），前端可渲染为快捷按钮引导用户切题。

### 2.1.1.1 Autonomous Grade Agent（规划→工具→反思→汇总）
- 入口：`homework_agent/services/autonomous_agent.py`
- 触发：**/grade 阶段**（单次调用完成识别/工具编排/判题汇总）
- 目标：通过“规划→工具→反思→汇总”的闭环，在成本/时延护栏内尽量产出可审计的结构化结果；当证据不足或触发安全/预算护栏时，走 `needs_review` 降级。
- qbank 持久化字段（用于 chat 复盘/路由）：
  - `qbank.questions[q_num].judgment_basis`（判定依据短句，供 chat 直接展示）
  - `qbank.questions[q_num].question_aliases`（非数字题名别名，用于 chat 路由）

**处理步骤**:
```python
1. 预处理/切片（可选增强）:
   ✅ 优先使用已有 qindex/切片缓存（若可用）
   ✅ 必要时用 VLM locator / OpenCV fallback 生成 ROI（best-effort）

2. Autonomous Grade Agent:
   ✅ Planner 规划：选择需要的工具（qindex_fetch/vision_roi_detect/ocr_fallback/math_verify…）
   ✅ Tools 执行：获得 OCR/ROI/校验证据（工具输出需带 ToolResult 统一字段）
   ✅ Reflect 反思：评估证据是否足够；不足则重规划，直到达标或触发护栏
   ✅ Aggregate 汇总：输出结构化判定（verdict + reason + judgment_basis + warnings）
```

**质量控制**:
- 非作业图 → rejected
- 证据不足/触发护栏 → verdict=uncertain + warnings + judgment_basis 说明依据来源，并触发 needs_review

### 2.3 阶段3：批改执行

#### SOP-3.1: 数学批改链
**调用prompt**: `MATH_GRADER_SYSTEM_PROMPT`

**处理逻辑**:
```python
1. 题目解析:
   ✅ 从识别结果中识别数学题目
   ✅ 分离题干和学生答案
   ✅ 检测题型（计算/几何/应用题）

2. 步骤级验证:
   ✅ 将学生解答分解为步骤
   ✅ 每步与标准解法对比
   ✅ 标记verdict: correct/incorrect/uncertain
   ✅ 分类severity: calculation/concept/format
   ✅ 可选bbox: 为步骤提供归一化bbox（若可信）

3. 几何分析:
   ✅ 识别几何元素（线/角/点）
   ✅ 验证辅助线绘制
   ✅ 检查标注完整性
   ✅ 生成自然语言描述

4. 知识标签:
   ✅ 自动打标 L2/L3 知识点
   ✅ 例: ['数学', '几何', '三角形', '全等判定']

5. 输出结构化（新版判定标准，务必覆盖所有题目）:
   ✅ 对每题提供：题干概要、学生作答（文本/选项）、标准答案、判定 is_correct；选项题写明 student_choice/correct_choice；未答标 missing。
   ✅ verdict 仅 correct/incorrect/uncertain；severity 仅 calculation/concept/format/unknown/medium/minor。
   ✅ wrong_items 仅含 incorrect/uncertain，但 summary 需说明全题覆盖（全对也说明“未发现错误”）；不确定时明确原因。
   ✅ 不编造 bbox，不确定时留空或省略 bbox。
   ✅ 返还 vision_raw_text 供前端/审计查看。
```

**边界情况处理**:
- 部分正确 → 在第一个错误步骤处停止详细分析
- 步骤缺失 → 在missing步骤处提示
- 几何图形模糊 → 使用uncertain verdict

#### SOP-3.2: 英语批改链
**调用prompt**: `ENGLISH_GRADER_SYSTEM_PROMPT`

**处理逻辑**:
```python
1. 答案理解:
   ✅ 提取学生答案和标准答案
   ✅ 忽略格式差异（标点、大小写）

2. 语义相似度计算:
   ✅ 使用LLM计算语义相似度
   ✅ Normal模式: 阈值0.85
   ✅ Strict模式: 阈值0.91 + 关键词检查

3. 关键词提取（Strict模式）:
   ✅ 自动识别标准答案中的1-3个关键术语
   ✅ 验证学生答案包含这些术语（或同义词）
   ✅ 记录keywords_used用于审计

4. 结果评估:
   ✅ 相似度≥阈值 AND 关键词匹配 → correct
   ✅ 否则 → incorrect
   ✅ 计算semantic_score (0-1)，填充 similarity_mode/keywords_used
```

### 2.4 阶段4：辅导对话

#### SOP-4.1: 报告式对话启动
**触发条件**: 学生进入对话或追问具体题目

**前置准备**:
```python
✅ 加载上下文:
  - 从GradeResponse加载错题/判定结果
  - 读取 vision_raw_text + judgment_basis（如有）
  - 初始化interaction_count = 0

✅ 输出策略:
  - 默认直接给出结论 + 解释（报告式）
  - 必须基于识别文本/judgment_basis，避免凭空补图
  - 若视觉信息不足：给出结论，但明确标注“依据不足，可能误读”
```

#### SOP-4.2: 对话循环（报告式输出 + 允许追问）
**调用prompt**: 以“结论 + 解释”为主（不再要求苏格拉底式引导）

**策略要点**:
```python
  - 仅在完成批改后使用（即便全对也可对话），不做纯闲聊。
  - 默认不限轮；用户可持续追问细节与依据。
  - 回答必须引用 vision_raw_text / judgment_basis 的事实描述。
  - 若视觉信息不足：加“依据不足，可能误读”的明确提示。
```

> SSE 心跳/断线：心跳建议 30s；若 90s 内无数据可断开；客户端可用 last-event-id 续接。

### 2.5 阶段5：结果输出

#### SOP-5.1: GradeResponse构建
**结构要求**:
```json
{
  "wrong_items": [/* WrongItem数组 */],
  "summary": "本次批改共检测到X道题，发现Y处错误",
  "subject": "math",
  "job_id": "job-xxx",  // 异步模式时
  "status": "done",
  "total_items": 5,
  "wrong_count": 2,
  "cross_subject_flag": false,
  "warnings": ["可能的警告"]
}
```

**质量检查**:
- wrong_count必须与wrong_items.length一致
- 若提供 bbox（或 bbox 列表），必须归一化且在 [0,1] 范围内；不确定则留空并写 warnings
- reason必须提供有用反馈
- 必须包含至少一个knowledge_tag

#### SOP-5.2: SSE流式输出
**事件序列**:
```http
1. heartbeat (30s间隔)
   {"timestamp": "2025-01-06T10:31:00Z"}

2. thinking (可选，多个)
   {"status": "analyzing|generating_hint", "progress": 0-100}

3. chat (多个消息片段)
   {"role": "assistant", "content": "...", "delta": true, "is_hint": true}

4. done (结束)
   {"session_id": "sess-xxx", "interaction_count": 2, "status": "continue"}
```

---

## 3. 决策树

### 3.1 科目识别决策树

```
输入图像内容
│
├─ 检测数学特征
│  ├─ 包含数学符号 (±, ∑, √, π, 几何图形) → 数学
│  ├─ 包含计算步骤 (竖式、代数变形) → 数学
│  └─ 纯文本，无数学特征 → 继续检查
│
└─ 检测英语特征
   ├─ 包含英文段落/句子 → 英语
   ├─ 包含英语词汇题/语法题 → 英语
   └─ 混合内容或无法确定 → 按用户选择的subject处理
```

### 3.2 错误严重程度判断

```
检测到错误
│
├─ 是否影响最终答案？
│  ├─ 是 → severity: calculation
│  └─ 否 → 继续判断
│
├─ 是否概念理解错误？
│  ├─ 是 → severity: concept
│  └─ 否 → 继续判断
│
├─ 是否格式/表达问题？
│  ├─ 是 → severity: format
│  └─ 否 → severity: unknown
```

### 3.3 辅导策略选择

```
学生当前问题
│
├─ 问题类型
│  ├─ "为什么错？" → 提供错误分析 + 提示
│  ├─ "怎么做？" → 提供解题思路引导
│  ├─ "不懂这步" → 聚焦特定步骤解释
│  └─ 其他 → 理解意图后选择策略
│
├─ 交互次数
│  ├─ ≤2次 → 轻提示策略
│  ├─ 3-4次 → 重提示策略
│  └─ 5次 → 完整解析策略
```

---

## 4. 错误处理策略

### 4.1 错误分类与处理

#### 4.1.1 输入验证错误
| 错误类型 | HTTP状态码 | 处理策略 |
|----------|-----------|----------|
| 缺少必需字段 | 400 | 明确指出缺失字段 |
| 无效图片格式 | 415 | 支持格式列表 |
| 图片过大 | 413 | 最大尺寸提示 |
| subject无效 | 400 | 支持的值列表 |

#### 4.1.2 处理错误
| 错误类型 | HTTP状态码 | 处理策略 |
|----------|-----------|----------|
| 视觉识别失败 | 422 | 返回部分结果 + warnings |
| 批改超时 | 408 | 返回中间结果 + status: processing |
| 会话过期 | 410 | 引导重新开始 |
| LLM服务错误 | 500 | 重试3次，仍失败返回错误 |

#### 4.1.3 限流错误
```python
# 429 Too Many Requests
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

### 4.2 异常恢复策略

#### 视觉识别异常恢复
```python
1. 第一次失败 → 自动重试（最多3次）
2. 仍失败 → 降级为不确定结论 + warnings
3. 完全失败 → 返回 {
   "wrong_items": [],
   "warnings": ["部分图片识别失败"]
}
```

#### LLM调用异常恢复
```python
1. 网络错误 → 指数退避重试（1s→2s→4s）
2. 配额不足 → 返回503，提示稍后重试
3. 模型不可用 → 自动切换备用模型
4. 全部失败 → 返回错误 + 建议联系支持
```

---

## 5. 质量保证

### 5.1 批改质量检查

#### 自动验证清单
```python
✅ 结构完整性:
  - 所有必需字段已填充
  - 没有空值在必需字段
  - 数组长度符合预期

✅ 数据一致性:
  - wrong_count = wrong_items.length
  - total_items ≥ wrong_count
  - 所有bbox在有效范围内[0,1]
  - cross_subject_flag 与 warnings 一致（仅标记，不切科）

✅ 内容质量:
  - reason提供有用反馈（非泛泛而谈）
  - hint是引导性问题（非直接答案）
  - knowledge_tags准确（与错误匹配）
  - English: semantic_score/similarity_mode/keywords_used 填充完整，阈值逻辑一致

✅ 逻辑检查:
  - verdict与reason一致
  - geometry_check描述与elements一致
  - severity合理（不是unknown除非真的未知）
```

#### 人工审核触发条件
- confidence < 0.7的识别结果
- geometry_check中uncertain状态
- cross_subject_flag = true
- 学生投诉的批改结果

### 5.2 辅导质量检查

#### 提示质量标准
```python
✅ 引导性:
  - 100%的问题形式（非陈述句）
  - 不包含直接答案或计算结果
  - 引导学生思考过程

✅ 针对性:
  - 基于具体错误内容
  - 符合学生当前水平
  - 简化复杂概念

✅ 鼓励性:
  - 肯定学生正确部分
  - 使用鼓励性语言
  - 保持耐心语气
```

#### 质量监控
```python
✅ 实时监控:
  - interaction_count > 5 立即触发
  - 学生多次问同一问题 → 调整策略
  - 学生表示困惑 → 提供更直接指导

✅ 事后分析:
  - 收集学生反馈评分
  - 分析哪些提示更有效
  - 持续优化prompt策略
```

---

## 6. 安全与隐私

### 6.1 数据保护

#### 敏感数据处理
```python
✅ 图像数据:
  - 原始图片（Submission）长期保留（除非用户删除（未来）或静默 180 天清理）
  - qindex 切片仅保留 7 天（可重建）
  - 传输中加密（HTTPS）
  - 存储加密（AES-256）

✅ 对话历史:
  - session_id关联存储
  - 7天后自动清理（不保证恢复旧对话上下文）

✅ 批改结果:
  - 错题数据用于个性化分析
  - 匿名化处理后用于模型训练（可选）
  - 不包含学生个人信息
```

#### 访问控制
```python
✅ API层面:
  - 需要有效的session_id才能访问对话
  - 限制并发会话数量（每用户5个）
  - 速率限制（防止滥用）

✅ 工具层面:
  - FastAPI 中间件/网关层进行权限控制与白名单校验
  - 不允许读取用户文件系统
  - 不允许网络访问（除必要的模型/API调用），并做限流
```

### 6.2 内容安全

#### 禁止处理的内容
- 包含个人身份信息（PII）的作业
- 涉及政治、色情、暴力的内容
- 非教育用途的图像

#### 违规处理
```python
1. 检测到违规内容 → 立即拒绝处理
2. 记录违规类型和来源
3. 返回错误: "内容不符合使用规范"
4. 累计违规 → 限制账户访问
```

---

## 7. 性能优化

### 7.1 批改性能

#### 优化策略
```python
✅ 图像处理:
  - 并行视觉调用（最多4张图同时）
  - 图像压缩（减少传输时间）
  - 缓存常用题型识别结果

✅ LLM调用:
  - 复用模型连接
  - 批量处理相似题目
  - 使用流式响应减少等待时间

✅ 结果缓存:
  - 相同作业ID返回缓存结果
  - 缓存有效期：按业务配置（幂等键默认 24h；chat_history 7d；切片 7d）
  - 缓存键：session_id / upload_id + subject + mode
```

#### 性能基准
```
✅ 批改性能目标:
  - 小批量(≤3张): <3秒同步返回
  - 大批量(>3张): <60秒异步处理
  - 单张图片视觉处理: <10秒（视模型与分辨率）

✅ 辅导性能目标:
  - 首次响应: <2秒
  - 后续交互: <1秒
  - SSE连接稳定性: 99%
```

### 7.2 资源管理

#### 内存管理
```python
✅ 会话生命周期:
  - 活跃会话: 常驻内存
  - 7天后: 清理对话历史（chat_history）
  - 静默180天: 清理用户数据（定时任务；以 last_active_at 为准）

✅ 图像缓存:
  - 处理中: 内存缓存
  - 处理完: 写入 Supabase Storage
  - 切片: 7天后自动清理（原始图片按 Submission 策略保留）
```

---

## 8. 监控与日志

### 8.1 关键指标

#### 性能指标
```python
✅ 批改指标:
  - 批改成功率 (>99%)
  - 平均批改耗时
  - 视觉识别准确率
  - 批改质量评分（人工反馈）

✅ 辅导指标:
  - 平均交互次数（目标: <3次）
  - 学生满意度
  - 辅导完成率
  - 重复问题率
```

#### 错误指标
```python
✅ 错误分类:
  - 输入验证错误率 (<1%)
  - 视觉识别失败率 (<5%)
  - LLM调用失败率 (<0.5%)
  - 超时错误率 (<1%)

✅ 告警阈值:
  - 批改成功率 < 95%
  - 批改耗时 > 60秒
  - 错误率 > 3%
  - SSE断开率 > 5%
```

### 8.2 日志规范

#### 必记录信息
```python
✅ 请求日志:
  - request_id, session_id, batch_id
  - 请求时间、耗时
  - 输入参数（脱敏）
  - 错误码和错误信息

✅ 批改日志:
  - 题目数量、错误数量
  - 使用的模型和prompt版本
  - 视觉识别置信度分布
  - 知识标签分布

✅ 辅导日志:
  - interaction_count
  - 提示策略选择
  - 学生反馈（如果有）
```

#### 日志格式
```json
{
  "timestamp": "2025-01-06T10:30:00Z",
  "level": "INFO",
  "request_id": "req-123",
  "session_id": "sess-456",
  "operation": "grade",
  "duration_ms": 1250,
  "success": true,
  "details": {
    "subject": "math",
    "total_items": 5,
    "wrong_count": 2,
    "model": "claude-sonnet-4-5"
  }
}
```

---

## 附录A: 快速参考

### A.1 常用命令

```python
# 启动 Agent 服务（FastAPI）
uvicorn homework_agent.main:app --host 127.0.0.1 --port 8000 --reload

# 运行测试
python3 -m pytest -q

# 启动 qindex worker（需要 Redis）
python3 -m homework_agent.workers.qindex_worker

# 验证脚本（按需）
./.venv/bin/pytest -q
```

### A.4 开发规则（团队约束）

- 工程级开发规则（P0→P2：评估门禁 / CI 分阶段 / Observe→Act→Evolve）以 `docs/development_rules.md` 为准。
- 可执行速查卡（命令 + checklist）以 `docs/development_rules_quickref.md` 为准。

### A.2 配置参数

```python
# 参考 .env.template / .env.example（节选）
DEV_USER_ID=dev_user
SLICE_TTL_SECONDS=604800  # 切片 7 天
CHAT_HISTORY_TTL_DAYS=7
SUBMISSION_INACTIVITY_PURGE_DAYS=180
```

### A.3 故障排除

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| 视觉识别失败 | 图片模糊/旋转 | 预处理图像，检查方向 |
| 批改结果不准确 | prompt需要调优 | 收集样本，优化prompt |
| SSE连接断开 | 网络不稳定 | 重连机制，last-event-id |
| 批改速度慢 | 模型响应慢 | 优化prompt，并行处理 |

---

## 文档维护

**Owner**: Homework Agent Team
**Review Cycle**: 每月审查一次
**Change Log**:
- v2.0.0 (2025-01-06): 全面升级，补充辅导流程、错误处理、性能要求
- v1.0.0 (初始版本): 基础批改流程
