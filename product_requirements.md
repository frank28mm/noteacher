# Product Requirements & Design Decisions

## 1. 核心业务流程与用户旅程 (Core Business Flow)

### 1.1 操作模式 (Input Workflow)
*   **用户角色**：家长 或 学生（均可操作）。
*   **上传路径（权威原图）**：前端仅负责把原始文件上传给后端；后端按 `user_id` 将原图落到云端存储（Supabase Storage），并返回 `upload_id`（一次上传=一次 Submission）与稳定的 `page_image_urls`。
    *   后续所有业务（`/grade`、`/chat`、qindex/relook）只围绕这份“权威原图”展开，避免“URL 不稳定/拉取失败/权限漂移”导致的看图失败。
*   **处理模式**：支持同步与异步两种（按图片数量与 SLA 自动选择）。
    *   用户拍摄多张作业照片（支持一次性上传，多页/PDF 拆页）。
    *   系统后台进行识别与批改；必要时转为异步任务（`job_id`）。
*   **覆盖科目**：仅限 **数学** 和 **英语**。

### 1.2 交互模式 (Interaction Mode)
*   **使用前提**：必须先完成一次批改（即便全对也行），基于该次 Submission 进入辅导；不做“纯闲聊”。
*   **指导风格**：**苏格拉底式引导 (Mode B)**。
    *   Agent **严禁**直接给出答案（辅导对话只给提示/反问/分步引导）。
    *   无通用 5 轮上限；当选定错题上下文时可按需要设置软性引导节奏，但默认不强制轮数封顶。
    *   **部分正确的引导策略**：
        * 定位优先级：逐步校验时只指出首个错误步骤；步骤均对但答案错时，提示“复核最后一步计算/抄写”，不直接给答案。
        * 提示递进：第1轮轻提示（复述已对部分，聚焦疑点）；第2轮方向提示（指出检查点/公式）；第3轮重提示（指出错误类型或位置，不给结果）。
        * 结构化反馈：`steps` 中用 `verdict` 标记 correct/incorrect/uncertain，可选 `severity`（计算错误/概念错误/格式）。
        * 几何题：作图对但标注缺失则提示标注；辅助线错误则指出错误线段/关系，但不直接给正确作法，按上述递进。
*   **答案获取**：如需提供完整答案/解析，必须在“非辅导对话”的独立页面/接口中提供；辅导对话中严禁直接给出答案。
*   **判定透明度**：批改结果需覆盖每道题，返回学生作答/标准答案/判定（选项题注明 student_choice/correct_choice），判定枚举受限（verdict 仅 correct/incorrect/uncertain；severity 仅 calculation/concept/format/unknown/medium/minor）；不确定要标记，禁止编造 bbox。返回 `vision_raw_text` 便于审计。
*   **Chat 首屏信息（产品要求）**：用户从批改进入 chat 页面时，首屏必须展示“批改结果 + 识别原文(vision_raw_text) + 原始图片”，让用户可快速校验系统工作质量。
    *   对话历史仅保留 7 天（定期清理）；超过 7 天再次进入仅展示该次 Submission 的批改结果与识别原文，不保证恢复旧对话上下文。

### 1.3 数据闭环 (Data Loop)
*   **权威事实（不可变）**：每次 Submission 都会长期保存：
    *   原始图片（以及必要时生成的轻量 proxy 副本）
    *   识别原文 `vision_raw_text`
    *   批改结果（summary/wrong_items/warnings…）
*   **错题的“删除”语义（可变视图）**：用户只能做“错题排除（只影响统计/报告）”，不修改历史事实。
    *   排除记录包含：`user_id + submission_id + item_id + excluded_at + reason`。
*   **学业报告（异步）**：报告基于一定时间段内的 submissions 聚合生成，可下载与查看历史报告；允许在未来“基于历史报告再生成报告”。

### 1.4 数据保留与清理 (Retention & Cleanup)
*   **长期保留（默认）**：原始图片 + 批改结果 + 识别原文，除非用户主动删除（未来）或触发系统级清理策略。
*   **短期保留（固定）**：
    *   Chat 对话历史：7 天（定期清理）
    *   qindex 切片：7 天（定期清理）
*   **静默清理（系统策略）**：用户长时间静默后清除其数据，阈值为 **180 天**（以 last_active_at 为准；由后台定时任务执行）。

## 2. Agent 能力边界 (Agent Capabilities)

### 2.1 识别能力 (Recognition)
*   **输入支持**：
    *   支持 **完全手写体** (如抄写本) 与 印刷体/手写混排。
    *   支持 **多图关联/跨页处理** (Cross-page context)，解决题目与答案分离或长篇阅读理解的问题。
    *   **学科边界**：严格遵循 `Subject` 字段。若数学作业中出现英语单词，或英语中出现计算式，除非影响题目理解，否则**忽略**非当前学科内容。

### 2.2 数学批改 (Math Grading)
*   **深度批改**：
    *   必须识别并校验 **计算过程** (Step-by-step verification)，而不仅是最终答案。
    *   必须支持 **几何图形识别** (Geometric figures)，能够判断辅助线、几何标记是否正确。
    *   **输出形式**：Phase 1 输出"结构化字段 + 文本描述"，不做图像标注坐标：
        * `steps` 数组：`index`, `verdict`(correct/incorrect/uncertain), `expected`, `observed`, `hint`（苏格拉底式引导），可选 `severity`/`category`（计算错误/概念错误/格式）。
        * `geometry`：文本判断（例：“辅助线 BE 画对了；∠ABC 标注缺失”），可选 `elements` 列表（type: line/angle/point; label: A,B,C; status: correct/missing/misplaced）。
    *   如后续需要步骤/几何高亮，可在错误项中补充可选 `bbox`，沿用统一坐标系。

### 2.3 英语批改 (English Grading)
*   **范围限制**：Phase 1 (MVP版本) **不包含** 作文批改。
*   **主观题逻辑**：**B. 语义相似度 (Semantic Similarity)**。
    *   判分以语义相似度为主：`normal` 档阈值默认 ~0.85，可微调；不做关键词硬性校验。
    *   `strict` 档：语义相似度阈值默认 ~0.91；LLM 自动从标准答案提炼 1–3 个关键术语做内部校验（默认 AND），需同时满足“相似度 ≥ 阈值且关键术语均出现”才判对。
    *   关键术语提炼对用户透明；无用户配置入口。如提炼失败/置信度低，则仅按语义相似度判定，避免误杀。

### 2.4 上下文与记忆 (Context & Memory)
*   **范围（辅导链）**：仅限于 **当前 Submission（单次上传）** 的批改上下文。
    *   能够识别本次作业中的重复错误模式并进行提示。
    *   不跨 Submission 调用历史记忆进行辅导（避免“拿旧作业推新作业”）。
*   **会话生命周期（对话历史）**：chat 对话历史保留 7 天；超过 7 天不保证可恢复对话，只保证可查看该次 Submission 的批改结果与识别原文。
*   **长期画像读写边界**：
    *   辅导链：默认只读本次 Submission（不读长期画像/历史错题）。
    *   报告链：可读取历史 submissions + 错题排除记录，用于长期分析与报告生成。
*   **跨学科/混合内容处理**：用户上传前需选择科目（数学/英语），系统按所选科目判题，默认不自动切科。
    * 轻量科目检测（OCR 特征）仅用于提示：若检测到与所选科目强冲突，可在报告标记“疑似科目不匹配”，不混用另一科模型。
    * 数学题为英文表述：仍按数学链处理；仅在数学特征极低且文本明显为英语阅读时提示可能不匹配。
    * 英语题含算式：仍按英语链处理，算式按文本处理，必要时提示“含算式，当前以英语语义相似度判定，可能影响准确度”。
    * 不做“双判”或自动切换科目，检测只做标记/提示，不中断批改。

## 3. 数据模型与个性化 (Data Model & Personalization)

### 3.1 错题数据结构 (Error Data Structure)
*   **双重存储策略**：
    *   **权威原图 (Authoritative Pages)**：保留整页原始快照（page_image_urls），用于审计/复核与后续再处理。
    *   **识别与判定快照 (Grading Snapshot)**：保留 vision_raw_text + 批改结果，用于 chat 首屏展示与长期追溯。
    *   **可选增强 (Review Slice)**：qindex 生成的题目切片（slice_image_urls），用于“看图辅导/定位/复习卡片”；切片仅保留 7 天，可重建但需算力与时间。
    *   **坐标系标准**：统一采用 **归一化坐标 (Normalized [0-1])** `[ymin, xmin, ymax, xmax]`，原点左上，y 向下，独立于分辨率，便于多端适配。
    *   **错题存储字段参考**：`page_image_url`（整页）、`slice_image_url`（裁剪片）、`page_bbox`（整页中的 bbox）、`review_slice_bbox`（题干+错答切片 bbox）；如需步骤级高亮，可在 steps/geometry 里使用相同归一化 bbox。

### 3.1.1 题目定位与切片（BBox + Slice，MVP 目标）
*   **bbox 的对象**：每道题的“整题区域”（题干 + 学生作答）。
*   **bbox 精度（MVP）**：允许框大一点，但应尽量不跨到别题（或跨得极少）。
*   **多页/跨页**：
    *   MVP 以“页内 bbox”为主；
    *   跨页题先退化为 **多 bbox** 或 **整页**（在 `warnings` 说明）。
*   **失败/不确定**：允许 `bbox=None` / `slice_image_url=None`，并在 `warnings` 写明“定位不确定，改用整页”。
*   **多 bbox 支持**：同一题可能分散在题干/作答两块区域，允许存为 bbox 列表。
*   **裁剪策略（MVP）**：
    *   坐标统一：bbox 归一化 `[ymin, xmin, ymax, xmax]`，裁剪时按原图像素尺寸换算；
    *   安全边距：默认在 bbox 四周加 5% padding；
    *   越界处理：裁剪前先 clamp 到 [0,1]；
    *   裁剪失败回退：不生成切片，只保留整页 URL + `warnings`。
*   **隐私与存储**：
    *   Demo 允许 public bucket；
    *   生产建议 signed URL（短期有效）；
    *   切片会增加存储量，必须有 TTL/清理策略（例如 24h 或 7d，按环境配置）。

### 3.2 学生画像粒度 (Student Profile Granularity)
*   **L2 知识点分类 (Knowledge Graph Tagging)**：
    *   利用 LLM 的通用知识能力进行**自动打标**。
    *   标签层级示例：`数学` -> `几何` -> `三角形` -> `全等三角形判定`。
*   **分析维度**：基于知识标签统计掌握率，生成“知识雷达图”。

## 4. 接口协议与架构 (Interface & Architecture)

### 4.1 通信协议 (Protocol)
*   **流式交互 (Streaming)**：采用 **SSE (Server-Sent Events)** 协议。
    *   目的：支持 Agent 较长的思考推理过程，实现“打字机”即时反馈效果，避免客户端超时等待。
    *   实时/流式场景（苏格拉底对话、小批量批改）：客户端/BFF ⇄ Python 直连 HTTP + SSE，单次超时 60s，可重试 1 次，需携带 idempotency-key 防重复；SSE 保持心跳，断线可选用 last-event-id 续接。
    *   异步长任务（批量/多页批改）：客户端/BFF 通过 HTTP 提交任务，Python 接收后内部入队（Redis）。状态回传可用 webhook 回调（失败重试 ≤3 次，指数退避）或轮询任务状态接口；任务创建请求超时 60s，可重试 1 次，需 idempotency-key。
    *   本仓库实现以 Python Agent + Redis worker 为主；BFF/前端可后续接入，不影响后端契约。

### 4.2 数据同步策略 (Data Sync)
*   **云端为本 (Cloud-First)**：
    *   核心数据（Submission：原始图片/识别原文/批改结果）存储在云端（Supabase Storage + Postgres），支持按时间查询与长期追溯。
    *   对话历史与切片为短期数据（默认 7 天），允许清理后不可恢复；客户端应优先展示 Submission 的批改结果与识别原文以保证可解释性。

### 4.3 服务形态 (Service Topology)
*   **独立 Agent 服务 (Microservice)**：
    *   将作业检查核心逻辑封装为独立的微服务 (Agent Service)。
    *   **内部通信**：BFF 与 Agent 之间采用 **HTTP (REST)** 直接调用，避免引入 MQ 增加复杂度。
    *   通过 API 网关对各端提供统一服务，实现核心业务逻辑解耦。
    *   说明：本仓库仅包含 Python Agent 与 qindex worker；BFF/客户端实现不在本仓库范围。

### 4.4 技术双引擎 (Dual-Engine Stack)
*   **前端交互层 (BFF)**（可选，未来）：Node.js (NestJS/Koa)
    *   处理 WebSocket/SSE 连接、业务逻辑、用户鉴权。
*   **AI 计算层 (Core Engine)**（本仓库实现）：Python (FastAPI)
    *   专注图像识别、批改推理、辅导对话与 qindex 切片生成。
