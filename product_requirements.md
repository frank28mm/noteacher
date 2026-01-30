# Product Requirements & Design Decisions

> **文档状态**: 已更新至代码实际实现（2026-01-30）  
> **当前阶段**: Beyond MVP - 功能完整的教育平台

## 功能实现状态总览

### ✅ 已完成功能 (Implemented)

#### 核心功能
- [x] **作业批改** (`/grade`): 数学/英语双科目，同步/异步双模式
- [x] **苏格拉底辅导** (`/chat`): SSE 流式对话，基于 Submission 上下文
- [x] **图片上传** (`/uploads`): 后端权威上传，支持 HEIC/PDF/多页
- [x] **题目定位** (qindex): bbox 定位 + 切片裁剪，24h TTL

#### 用户系统
- [x] **多认证方式**: 短信验证码、邮箱登录
- [x] **JWT 鉴权**: 完整 token 签发/验证/刷新
- [x] **家庭多档案**: 家长账号下多子女数据隔离 (`/me/profiles`)
- [x] **个人中心**: 账户管理、密码修改、邮箱绑定

#### 支付与计费
- [x] **配额系统**: BT (Brain Token) + CP (Compute Point) 双轨计费
- [x] **订阅系统**: 订阅订单创建、Mock 支付 (`/subscriptions/orders`)
- [x] **兑换卡系统**: 兑换码生成、分发、兑换 (`/subscriptions/redeem`)
- [x] **钱包管理**: 配额查询、使用记录

#### 数据与报告
- [x] **错题本**: 历史错题聚合、排除/恢复、统计 (`/mistakes`)
- [x] **学情报告**: 异步生成、历史查看、资格检查 (`/reports`)
- [x] **提交历史**: 按时间查询、详情查看、移动档案 (`/submissions`)
- [x] **数据归档**: 长期保存原始图片 + 批改结果

#### 运营支持
- [x] **用户反馈**: 提交反馈、管理员回复、未读检查 (`/feedback`)
- [x] **管理员后台**: 用户管理、钱包调整、兑换卡批量生成 (`/admin`)
- [x] **审计日志**: 操作记录、使用统计
- [x] **审核队列**: 高风险题目人工复核 (`/review`)

### 🔄 实验性功能 (Experimental)
- [ ] **Autonomous Grade Agent**: 规划-工具-反思-汇总流程（稳定性待验证）
- [ ] **视觉事实抽取 (VFE)**: 几何/图表视觉理解（门槛待固化）

### ⏳ 规划功能 (Planned)
- [ ] **原生 App 支持**: iOS/Android/HarmonyOS 客户端
- [ ] **BFF 层**: 仅在多客户端时考虑引入
- [ ] **GraphQL API**: 按需评估

---

## 1. 核心业务流程与用户旅程 (Core Business Flow)

### 1.1 操作模式 (Input Workflow)
*   **用户角色**：家长 或 学生（均可操作）。
*   **上传路径（权威原图）**：前端仅负责把原始文件上传给后端；后端按 `user_id` 将原图落到云端存储（Supabase Storage），并返回 `upload_id`（一次上传=一次 Submission）与稳定的 `page_image_urls`。
    *   后续所有业务（`/grade`、`/chat`、qindex、统一阅卷 Agent）只围绕这份“权威原图/切片”展开，避免“URL 不稳定/拉取失败/权限漂移”导致的看图失败。
*   **处理模式**：支持同步与异步两种（按图片数量与 SLA 自动选择）。
    *   用户拍摄多张作业照片（支持一次性上传，多页/PDF 拆页）。
    *   系统后台进行识别与批改；必要时转为异步任务（`job_id`）。
    *   **多页体验（建议，Demo 优先）**：允许“逐页可用”——第 1 页先出摘要/错题，不必等待全部页完成；UI 应显示 `X/N` 进度与“仍在批改中”的提示。
*   **覆盖科目**：仅限 **数学** 和 **英语**。

### 1.2 交互模式 (Interaction Mode)
*   **使用前提**：必须先完成一次批改（即便全对也行），基于该次 Submission 进入辅导；不做“纯闲聊”。
    *   **多页批改进行中（建议，方案 A）**：允许用户对“已完成页/已完成题目”先进入辅导；chat 必须显式标注“当前仅基于已完成页（1..X）回答”，不得引用未完成页内容。
*   **指导风格**：**苏格拉底式辅导（以提问与提示为主）**（以当前主 prompt 为准）。
    *   默认不直接给最终答案，优先用连续提问引导学生自己发现错误；必要时按轮次递进提示（轻提示/方向提示/重提示）。
    *   回答必须基于 `/grade` 产出的题干/作答/`judgment_basis`/`vision_raw_text` 摘要等证据；证据不足时必须明确标注“不确定/依据不足”。
    *   结构化反馈：`steps` 中用 `verdict` 标记 correct/incorrect/uncertain，可选 `severity`（计算错误/概念错误/格式）。
*   **判定透明度**：批改结果需覆盖每道题，返回学生作答/标准答案/判定（选项题注明 student_choice/correct_choice），判定枚举受限（verdict 仅 correct/incorrect/uncertain；severity 仅 calculation/concept/format/unknown/medium/minor）；不确定要标记，禁止编造 bbox。返回 `vision_raw_text` 便于审计，并输出 `judgment_basis` 作为用户可读依据。
*   **题目定位体验**：用户可用数字题号或非数字题名（如“思维与拓展/旋转题”）发起辅导；若无法定位，必须返回候选题目列表，并在 UI 中提供可点击按钮进行切题。
*   **Chat 首屏信息（产品要求）**：用户上传图片批改成功后，首屏必须在 **同一聊天页面** 展示：
    *   识别原文（vision_raw_text）
    *   判定依据（judgment_basis，中文短句清单）
    *   批改结果（结论 + 解释）
    *   会话/对话历史按 `session_id` 的 **24 小时生命周期**（与契约一致）；超过 24 小时再次进入仅展示该次 Submission 的批改结果与识别原文，不保证恢复旧对话上下文。

### 1.2.1 图形题一致性（产品要求：看图要可信）
*   **目标**：几何/图表/示意图这类题，**答案必须基于视觉理解**；允许“有依据地错”，但必须可复盘、可解释。
*   **实现策略（稳定优先，MVP）**：
    *   **统一阅卷 Agent**：视觉识别与批改合一，输出 `vision_raw_text + judgment_basis + grading_result`，不再拆分为独立“视觉事实抽取”链路。
    *   **OpenCV 前置流水线**：去噪/矫正/切片为固定流程；Agent 直接使用高质量切片（figure + question 双图优先）。
    *   **Chat 只读 /grade 产出**：使用 `judgment_basis + vision_raw_text` 作为对话依据，不做实时 relook。
    *   **不阻断输出**：若视觉信息不足仍给出结论，但必须在 `warnings` 说明“依据不足/可能误读”，并在 `judgment_basis` 写明依据来源。

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
    *   会话/对话历史：默认 24 小时（与 `session_id` 生命周期一致）
    *   qindex 切片：默认 24 小时（由 `SLICE_TTL_SECONDS` 控制）
    *   judgment_basis：随 qbank/Submission 快照保存（结构化短句列表），用于审计/复盘；若未来对 qbank 做 TTL，随之清理。
*   **用户数据治理（不在本服务范围）**：静默清理/长期数据生命周期属于上层“用户与数据管理后台”的职责，本服务仅按契约处理会话/切片等短期数据。

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
        * `steps` 数组：`index`, `verdict`(correct/incorrect/uncertain), `expected`, `observed`, `hint`（解释/提示），可选 `severity`/`category`（计算错误/概念错误/格式）。
        * `geometry`：文本判断（例：“辅助线 BE 画对了；∠ABC 标注缺失”），可选 `elements` 列表（type: line/angle/point; label: A,B,C; status: correct/missing/misplaced）。
    *   如后续需要步骤/几何高亮，可在错误项中补充可选 `bbox`，沿用统一坐标系。

#### 2.2.1 /grade 快路径与视觉路径（当前实现口径）

> 目的：在“可运营闭环”的前提下，把体验做稳——文本题优先走稳定快路径，图形题走可解释的视觉证据路径。

*   **快路径（默认）**：适用于绝大多数“纯文本/算式/无图形证据”的页面。
    *   默认配置：`AUTONOMOUS_PREPROCESS_MODE=qindex_only` + `GRADE_IMAGE_INPUT_VARIANT=url`
    *   行为：先 OCR（可缓存）→ 以 OCR 文本为证据进行结构化聚合输出（可审计：`ark_response_id` + `timings_ms`）
    *   约束：证据不足必须标记 `uncertain/needs_review`，禁止“看起来很快但互相矛盾”的结论。
*   **视觉路径（待专项验证后固化门槛）**：用于几何/函数图像/复杂示意图等需要“看图”才能可靠判定的场景。
    *   行为：优先生成/复用 figure/question 切片（qindex/opencv；必要时 VLM locator）→ 再启用 `image_process` 做放大/定位/复核
    *   目标：在视觉题上保证“可解释/可复核”，宁可 `uncertain` 也不误判为 `correct`

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
*   **会话生命周期（对话历史）**：按 `session_id` 的 24 小时生命周期；超过 24 小时不保证可恢复对话，只保证可查看该次 Submission 的批改结果与识别原文。
*   **长期画像读写边界**：
    *   辅导链：默认只读本次 Submission（不读长期画像/历史错题）。
    *   报告链：可读取历史 submissions + 错题排除记录，用于长期分析与报告生成。
*   **跨学科/混合内容处理**：用户上传前需选择科目（数学/英语），系统按所选科目判题，默认不自动切科。
    * 轻量科目检测（识别特征）仅用于提示：若检测到与所选科目强冲突，可在报告标记“疑似科目不匹配”，不混用另一科模型。
    * 数学题为英文表述：仍按数学链处理；仅在数学特征极低且文本明显为英语阅读时提示可能不匹配。
    * 英语题含算式：仍按英语链处理，算式按文本处理，必要时提示“含算式，当前以英语语义相似度判定，可能影响准确度”。
    * 不做“双判”或自动切换科目，检测只做标记/提示，不中断批改。

## 3. 数据模型与个性化 (Data Model & Personalization)

### 3.1 错题数据结构 (Error Data Structure)
*   **双重存储策略**：
    *   **权威原图 (Authoritative Pages)**：保留整页原始快照（page_image_urls），用于审计/复核与后续再处理。
    *   **识别与判定快照 (Grading Snapshot)**：保留 vision_raw_text + 批改结果，用于 chat 首屏展示与长期追溯。
    *   **可选增强 (Review Slice)**：qindex 生成的题目切片（slice_image_urls），用于“看图辅导/定位/复习卡片”；切片默认仅保留 **24 小时**（可配置），过期可重建但需算力与时间。
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
        *   切片会增加存储量，必须有 TTL/清理策略（默认 24h，可按环境配置）。

### 3.2 学生画像粒度 (Student Profile Granularity)
*   **L2 知识点分类 (Knowledge Graph Tagging)**：
    *   利用 LLM 的通用知识能力进行**自动打标**。
    *   标签层级示例：`数学` -> `几何` -> `三角形` -> `全等三角形判定`。
*   **分析维度**：基于知识标签统计掌握率，生成“知识雷达图”。

### 3.3 家庭-子女档案（Child Profiles，用于数据隔离）

> 注意：这里的 “Profile/档案” 指 **一个家长账号下的多个子女数据视图**，用于把历史记录/错题/报告隔离开；它与 3.2 的“学生画像/知识画像”不是一回事。

**已确认决策（v1）**
*   **配额/计费归属**：以家长主账号 `user_id` 为计费主体，家庭共用配额（不按孩子独立计费）。
*   **隔离维度**：所有业务数据读写按 `(user_id, profile_id)` 隔离；切换孩子后，全站仅展示该 `profile_id` 下的数据。
*   **命名规则**：同一家庭（同一 `user_id`）下孩子的 `display_name` 必须唯一（否则家长无法区分）。
*   **体验策略**：不做“上传前阻断式选择”；采用：
    *   **强提示**：在拍照/上传/开始批改等关键动作处明确展示 `提交到：<孩子名>`；
    *   **可补救**：允许把一次作业（submission）移动到另一个孩子（避免忘记切换造成的数据串号）。

**后端契约口径**
*   前端应在业务请求头携带 `X-Profile-Id`（若已选择孩子）；未携带时后端自动落到默认 profile（兼容旧客户端）。
*   Profiles 相关接口/行为详见：`homework_agent/API_CONTRACT.md` 与 `docs/profile_management_plan.md`。

---

## 5. 业务功能模块详解

### 5.1 支付与计费系统 (Payment & Billing)

#### 5.1.1 配额体系 (Quota System)

**钱包字段** (user_wallets 表):
*   `bt_trial`: 试用额度（新用户赠送）
*   `bt_subscription`: 订阅总额度
*   `bt_subscription_active`: 激活的订阅额度
*   `bt_subscription_expired`: 过期的订阅额度（30天后过期）
*   `bt_report_reserve`: 报告生成预留额度
*   `report_coupons`: 报告券数量（独立配额）

**BT 计算规则** (WS-E frozen rule):
```
BT = prompt_tokens + 10 × completion_tokens
```

**CP (Compute Point) 转换**:
```
CP = BT // 12400
```
显示给用户的最小单位是 CP，但计费按 BT 精确扣除。

**消耗顺序**:
1. 先消耗 `bt_trial`（试用额度）
2. 再消耗 `bt_subscription_active`（激活的订阅额度）
3. 报告生成消耗 `report_coupons` → 再消耗 `bt_report_reserve`

**额度过期**:
*   订阅额度 30 天后自动过期（expiry_worker 处理）
*   过期后 `bt_subscription_active` → `bt_subscription_expired`

#### 5.1.2 订阅系统 (Subscription)
*   **订单创建**: `POST /subscriptions/orders`
    *   创建订阅订单（月度/年度）
    *   返回订单 ID 和支付信息
*   **Mock 支付**: `POST /subscriptions/orders/{id}/mock_pay` (开发环境)
    *   模拟支付成功，用于测试
*   **实际支付**: 生产环境对接支付宝/微信支付 (待接入)

#### 5.1.3 兑换卡系统 (Redemption)
*   **兑换码生成** (管理员): `POST /admin/redeem_cards/generate`
    *   批量生成兑换码（指定 BT 额度、有效期）
    *   支持批次管理、禁用批次
*   **兑换流程** (用户): `POST /subscriptions/redeem`
    1. 用户输入兑换码
    2. 验证兑换码有效性（未使用、未过期）
    3. 将对应 BT 额度加入用户钱包
    4. 记录兑换历史
*   **查询**: `GET /subscriptions/redemptions`
    *   查看个人兑换历史

### 5.2 用户反馈系统 (Feedback)

#### 5.2.1 用户侧功能
*   **提交反馈**: `POST /feedback`
    *   支持文本反馈
    *   支持上传图片（images 字段，图片 URL 列表）
*   **查看反馈**: `GET /feedback`
    *   分页查看个人反馈历史
    *   显示管理员回复状态
    *   自动标记管理员消息为已读
*   **未读检查**: `GET /feedback/check_unread`
    *   检查是否有管理员新回复

#### 5.2.2 管理员侧功能
*   **用户列表**: `GET /admin/feedback/users`
    *   查看有反馈的用户列表
*   **查看反馈**: `GET /admin/feedback/{user_id}`
    *   查看特定用户的所有反馈
*   **回复反馈**: `POST /admin/feedback/{user_id}`
    *   管理员回复用户反馈
    *   标记为已处理

### 5.3 管理员后台 (Admin)

#### 5.3.1 用户管理
*   **用户列表**: `GET /admin/users`
    *   分页查询所有用户
    *   支持按注册时间、配额筛选
*   **用户详情**: `GET /admin/users/{id}`
    *   查看用户完整信息（账户、钱包、档案）
*   **钱包调整**: `POST /admin/users/{id}/wallet_adjust`
    *   手动调整用户 BT 额度（补偿/奖励）
    *   支持分池调整：试用额度(bt_trial)、订阅额度(bt_subscription)、报告预留(bt_report_reserve)
    *   请求体：`{ "bt_trial_delta": 0, "bt_subscription_delta": 50000, "bt_report_reserve_delta": 0, "reason": "补偿" }`
*   **配额授予**: `POST /admin/users/{id}/grant`
    *   批量授予订阅或报告券

#### 5.3.2 数据审计
*   **审计日志**: `GET /admin/audit_logs`
    *   查看管理员操作记录
*   **使用记录**: `GET /admin/usage_ledger`
    *   查看系统资源使用统计
*   **提交查询**: `GET /admin/submissions`
    *   查看所有用户提交
*   **报告查询**: `GET /admin/reports`
    *   查看所有生成报告

#### 5.3.3 运营统计
*   **仪表盘**: `GET /admin/stats/dashboard`
    *   日活/月活用户
    *   批改量统计
    *   收入统计

### 5.4 数据归档与复习 (Archive & Review)

#### 5.4.1 数据归档 (Data Archive)
*   **长期保留**: 原始图片 + 批改结果 + 识别原文
*   **查看历史**: 按时间轴查看所有提交
*   **跨档案移动**: 支持将提交移动到不同子女档案

#### 5.4.2 错题复习 (Review Flow)
*   **错题本**: 聚合历史所有错题
*   **排除机制**: 标记已掌握的错题（不影响统计）
*   **复习卡片**: 系统自动生成复习计划
*   **审核队列**: 高风险错题进入人工复核

## 4. 接口协议与架构 (Interface & Architecture)

### 4.1 通信协议 (Protocol)
*   **流式交互 (Streaming)**：采用 **SSE (Server-Sent Events)** 协议。
    *   目的：支持 Agent 较长的思考推理过程，实现“打字机”即时反馈效果，避免客户端超时等待。
    *   实时/流式场景（苏格拉底式辅导、小批量批改）：前端 ⇄ FastAPI 直连 HTTP + SSE，单次超时 60s，可重试 1 次，需携带 idempotency-key 防重复；SSE 保持心跳，断线可选用 last-event-id 续接。
    *   异步长任务（批量/多页批改）：前端通过 HTTP 提交任务，后端接收后内部入队（Redis）。状态回传可用 webhook 回调（失败重试 ≤3 次，指数退避）或轮询任务状态接口；任务创建请求超时 60s，可重试 1 次，需 idempotency-key。
    *   本仓库实现以 FastAPI + Redis Worker 为主；前端 React 应用直接调用后端 API。

### 4.2 数据同步策略 (Data Sync)
*   **云端为本 (Cloud-First)**：
    *   核心数据（Submission：原始图片/识别原文/批改结果）存储在云端（Supabase Storage + Postgres），支持按时间查询与长期追溯。
    *   对话历史与切片为短期数据（默认 24h），允许清理后不可恢复；客户端应优先展示 Submission 的批改结果与识别原文以保证可解释性。

### 4.3 服务形态 (Service Topology)
*   **独立后端服务 (Microservice)**：
    *   将作业检查核心逻辑封装为独立的后端服务 (FastAPI)。
    *   **前端通信**：前端 React 应用直接调用后端 **HTTP (REST)** API，无需 BFF 层。
    *   通过 API 网关对外提供统一服务（生产环境建议使用阿里云 API Gateway）。
*   说明：本仓库包含 FastAPI 主服务与多个后台 workers（grade/qindex/facts/report/review_cards/expiry）；前端实现在 `homework_frontend/` 目录。

### 4.4 技术栈 (Tech Stack)

#### 前端层 (Frontend)
*   **框架**: React 19 + TypeScript 5.9
*   **构建**: Vite 7.2
*   **样式**: Tailwind CSS 3.4
*   **数据**: axios + SWR
*   **路由**: react-router-dom 7
*   **动画**: framer-motion
*   **数学渲染**: KaTeX
*   **目录**: `homework_frontend/`

#### 后端层 (Backend)
*   **框架**: FastAPI (Python 3.10+)
*   **AI 模型**: Doubao (Ark) + Qwen3 (SiliconFlow)
*   **数据库**: Supabase (PostgreSQL + Storage)
*   **缓存/队列**: Redis
*   **部署**: 阿里云 ACK + ECI + PolarDB
*   **目录**: `homework_agent/`

#### 工作流 (Workers)
*   `grade_worker`: 异步批改
*   `qindex_worker`: 题目定位与切片
*   `facts_worker`: 事实特征提取
*   `report_worker`: 学情报告生成
*   `review_cards_worker`: 复习卡片生成
*   `expiry_worker`: 过期数据清理
