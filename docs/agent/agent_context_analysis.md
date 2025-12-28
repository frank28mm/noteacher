# Context Engineering 对比分析

> 本文档基于 Google《Context Engineering: Sessions & Memory》白皮书，分析"作业检查大师"项目的上下文工程实现，评估其与文档标准的符合度。

**分析日期**: 2025-12-27
**参考文档**: Context Engineering_ Sessions & Memory.md
**分析范围**: Session 管理、上下文组装、长期记忆

---

## 1. 执行摘要

### 1.1 核心发现

| 维度 | 文档要求 | 当前实现 | 符合度 |
|------|---------|---------|--------|
| **Sessions (会话)** | Events + State 分离 | ⚠️ State 很强；Events 记录不完整 | **8/10** |
| **Context Engineering** | 动态上下文组装 | ✅ 部分符合 | **7/10** |
| **Session 持久化** | 数据库存储 | ⚠️ Cache with TTL | **6/10** |
| **Context Compaction** | 压缩策略 | ⚠️ 主要依赖迭代上限（非正式 compaction） | **5/10** |
| **长期记忆 (Memory)** | 跨会话持久化 | ❌ 缺失 | **2/10** |
| **多 Agent 协作** | 共享/分离历史 | ⚠️ 单一运行时 | **4/10** |
| **生产就绪度** | 安全、性能、完整性 | ⚠️ 性能较好；隔离/脱敏/审计不足 | **5/10** |

### 1.2 关键差距

| 优先级 | 差距项 | 影响 | 工作量 |
|--------|--------|------|--------|
| **P0** | 缺少隔离/脱敏/事件化/审计 | 多租户/PII 风险 + 难排障回放，影响生产可用性 | 中 |
| **P1** | Session 压缩策略不完善 | 长对话性能问题 | 中 |
| **P1** | 缺少长期记忆 (Memory) | 无法跨会话学习/沉淀“最佳路径” | 高 |
| **P2** | 未实现多 Agent 历史共享 | 当前架构不需要，但会限制未来扩展 | 低 |

---

## 2. Context Engineering 概念对比

### 2.1 文档核心定义

**Context Engineering** 是从 **Prompt Engineering** 进化而来：

| 特征 | Prompt Engineering | Context Engineering |
|------|-------------------|---------------------|
| **关注点** | 静态系统指令 | 动态上下文组装 |
| **组成部分** | System Instructions | System Instructions + Tools + Evidence + History + State + User Query |
| **数据源** | 硬编码提示词 | RAG 数据库 + Session Store + Memory Manager |
| **比喻** | 食谱 | 备料 (mise en place) |

**文档中的上下文组成**:

```
┌─────────────────────────────────────────────────────────┐
│              Context Payload 组成                         │
├─────────────────────────────────────────────────────────┤
│ 1. Context to guide reasoning (推理指导)                 │
│    - System Instructions: Agent 的人设和约束              │
│    - Tool Definitions: 工具 Schema                        │
│    - Few-Shot Examples: 示例                              │
├─────────────────────────────────────────────────────────┤
│ 2. Evidential & Factual Data (证据和事实数据)              │
│    - Long-Term Memory: 用户/主题的长期记忆                 │
│    - External Knowledge: RAG 检索的外部知识               │
│    - Tool Outputs: 工具返回的数据                         │
│    - Sub-Agent Outputs: 子 Agent 的结论                   │
├─────────────────────────────────────────────────────────┤
│ 3. Immediate conversational information (即时对话信息)    │
│    - Conversation History: 对话历史记录                   │
│    - State / Scratchpad: 临时工作记忆                      │
│    - User's Prompt: 用户当前查询                          │
└─────────────────────────────────────────────────────────┘
```

### 2.2 你的项目实现对比

#### 2.2.1 Context Engineering 流程 - 符合

文档描述的 Context Engineering 循环：

```
1. Fetch Context → 2. Prepare Context → 3. Invoke LLM/Tools → 4. Upload Context
```

你的项目实现（概念映射，简化摘录；以 `run_autonomous_grade_agent()` 为核心）：

```python
# 1. Fetch/Build Context (构建会话状态容器)
state = SessionState(session_id=session_id, image_urls=images)

# 2. Prepare Context (预处理：切片/索引/元数据 → 写入 state)
pipeline = PreprocessingPipeline(session_id=session_id)
for image in images:
    result = await pipeline.process_image(image, use_cache=True)
    # 写入 state.slice_urls / state.preprocess_meta / state.warnings ...

# 3. Invoke LLM/Tools (Planner → Executor → Reflector，多轮迭代)
for _ in range(max_iterations):
    plan = await planner_agent.run(state)      # Think
    await executor_agent.run(state, plan)      # Act
    reflection = await reflector_agent.run(...)# Observe
    if reflection.pass_ and reflection.confidence >= threshold:
        break

# 4. Upload Context (持久化：保存会话状态，便于排障/回放/短期续跑)
get_session_store().save(state.session_id, state)
```

**符合度**: ✅ **8/10** - 核心循环吻合；但缺“完整事件流（events）”的标准化记录与长期记忆生成（Upload/Background）

#### 2.2.2 上下文组成部分 - 部分符合

| 组成部分 | 文档要求 | 项目实现 | 状态 |
|---------|---------|---------|------|
| **System Instructions** | Agent 人设和约束 | ✅ `PLANNER_SYSTEM_PROMPT` | ✅ |
| **Tool Definitions** | 工具 Schema | ⚠️ 工具描述在 prompt 中（非严格 schema） | ⚠️ |
| **Few-Shot Examples** | 示例引导 | ⚠️ 视具体 prompt 而定（整体偏少） | ⚠️ |
| **Long-Term Memory** | 跨会话记忆 | ❌ 缺失 | ❌ |
| **External Knowledge** | RAG 检索 | ❌ 无 RAG | ❌ |
| **Tool Outputs** | 工具结果 | ✅ `state.tool_results` | ✅ |
| **Conversation History** | 对话历史 | ⚠️ `state.plan_history` 更偏“规划轨迹”，未覆盖完整 tool_call/tool_output/user_input 事件流 | ⚠️ |
| **State / Scratchpad** | 工作记忆 | ✅ `SessionState` dataclass | ✅ |
| **User's Prompt** | 当前查询 | ✅ `images` + `subject` | ✅ |

**符合度**: ⚠️ **6/10** - 基础组件完善；缺 Memory/RAG；且 tool schema 与事件化 history 仍可加强

---

## 3. Sessions (会话管理) 对比

### 3.1 文档定义

**Session** 是单个对话的容器，包含两部分：

1. **Events (事件)**: 按时间顺序的对话记录
   - user_input: 用户消息
   - agent_response: Agent 回复
   - tool_call: 工具调用
   - tool_output: 工具返回

2. **State (状态)**: 结构化的工作记忆
   - 购物车内容
   - 临时变量
   - 计算中间结果

### 3.2 你的项目实现

#### 3.2.1 SessionState 结构 - 完全符合 ✅

**你的实现** ([session_state.py:16-30](homework_agent/services/session_state.py#L16)):

```python
@dataclass
class SessionState:
    session_id: str                      # 会话标识
    image_urls: List[str]                # 输入图片
    slice_urls: Dict[str, List[str]]     # 切片结果
    ocr_text: Optional[str]              # OCR 提取的文本
    plan_history: List[Dict[str, Any]]   # ⚠️ 规划轨迹（事件子集）
    tool_results: Dict[str, Any]         # ✅ Tool Outputs
    reflection_count: int                # ✅ State (计数器)
    partial_results: Dict[str, Any]      # ✅ State (临时结果)
    slice_failed_cache: Dict[str, bool]  # ✅ State (失败缓存)
    attempted_tools: Dict[str, Dict]     # ✅ State (工具状态)
    preprocess_meta: Dict[str, Any]       # ✅ State (元数据)
    warnings: List[str]                  # ✅ State (警告累积)
```

**分析**:
- ✅ **规划轨迹记录**: `plan_history` 记录每次 Planning 的输入/输出与部分轨迹信息
- ⚠️ **完整 Events 不足**: user_input/tool_call/tool_output/agent_response 未统一建模为事件流（部分信息分散在 `tool_results` 与日志里）
- ✅ **丰富的 State 管理**: 包含工具状态、缓存、计数器、临时结果
- ✅ **序列化支持**: `to_dict()` / `from_dict()` 完整支持持久化

**符合度**: ✅ **8/10** - State 设计优秀；若补齐“事件流模型”会更贴近白皮书 Session 定义

#### 3.2.2 Session 持久化 - 部分符合 ⚠️

**文档要求**:
- 生产环境使用数据库 (Agent Engine Sessions, Spanner, Redis)
- 需要安全隔离 (ACL)
- 需要 TTL 生命周期管理

**你的实现** ([session_state.py:77-100](homework_agent/services/session_state.py#L77)):

```python
class CacheSessionStore(SessionStore):
    def __init__(self, *, ttl_seconds: Optional[int] = SESSION_TTL_SECONDS):
        self._cache = get_cache_store()  # Redis 缓存
        self._ttl_seconds = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"autonomous:state:{session_id}"
```

**符合点**:
- ✅ 使用 Redis 存储 (符合文档推荐)
- ✅ TTL 支持 (默认 SESSION_TTL_SECONDS)
- ✅ 抽象接口设计 (`SessionStore` ABC)

**改进点**:
- ⚠️ 缺少用户级隔离 (无 user_id 绑定)
- ⚠️ 缺少 ACL 权限控制
- ⚠️ 缺少数据完整性保证 (如顺序保证)

**符合度**: ⚠️ **6/10** - 基础设施完善，生产级特性不足

---

## 4. Context Compaction (上下文压缩) 对比

### 4.1 文档要求

随着对话增长，需要压缩策略以：
- 降低 API 成本
- 减少延迟
- 避免 "context rot" (上下文腐烂)
- 控制在 context window 限制内

**文档推荐的压缩策略**:

| 策略 | 描述 | 适用场景 |
|------|------|----------|
| **Keep Last N Turns** | 滑动窗口，只保留最近 N 轮 | 简单实现 |
| **Token-Based Truncation** | 按 token 数量截断 | 需要精确控制 |
| **Recursive Summarization** | 旧消息替换为 AI 摘要 | 长对话 |

**触发机制**:
- Count-Based: 达到阈值触发
- Time-Based: 闲置时间触发
- Event-Based: 任务完成触发

### 4.2 你的项目实现

#### 4.2.1 当前压缩策略 - 部分实现 ⚠️

**你的实现现状**:
- 当前并没有显式的“Context Compaction”组件（没有对 `plan_history/tool_results` 做 token 预算压缩）。
- 之所以短期还能跑通，主要依赖两类“硬上限”：
  - `max_iterations` 限制了 `plan_history` 的长度（默认 3）
  - 每次 LLM 调用有 `max_tokens` 上限，且上下文来源相对固定

**分析**:
- ✅ **短期可控**：在任务式 Agent + 迭代次数有限的前提下，不太容易爆 context window
- ⚠️ **一旦事件化/链路变长会暴露问题**：引入 `events[]`、更多工具、更多轮反思后，需要真正的 token 预算与摘要策略

#### 4.2.2 缺失的压缩策略

**文档推荐但未实现的**:

| 策略 | 重要性 | 实施难度 |
|------|--------|----------|
| Token-Based Truncation | 中 | 低 |
| Recursive Summarization | 高 | 中 |
| 动态触发机制 | 中 | 中 |

**建议**:
1. **短期**: 先事件化（A.0 / 8.1），明确“压缩对象是谁”（建议以 `events[]` 为事实来源）
2. **中期**: 实现 Token-Based Compaction（对 `events[]` 做预算 + summary 事件）
3. **长期**: 必要时再引入 Recursive Summarization（超长上下文场景）

**符合度**: ⚠️ **5/10** - 有基础实现，缺高级策略

---

## 5. Memory (长期记忆) 对比

### 5.1 文档定义

**Memory** 是跨会话持久化的关键信息提取，与 Session 不同：

| 特征 | Session | Memory |
|------|---------|--------|
| **时间范围** | 单次对话 | 跨多次对话 |
| **数据格式** | 原始事件 | 提取的信息 |
| **组织方式** | 按时间顺序 | 按主题/实体 |
| **目的** | 对话连贯性 | 长期个性化 |

**Memory vs RAG**:

| 维度 | RAG | Memory |
|------|-----|--------|
| **数据源** | 外部文档 (PDF, Wiki) | 对话历史 |
| **隔离性** | 全局共享 | 用户级隔离 |
| **数据类型** | 静态、权威 | 动态、用户特定 |
| **触发方式** | Agent 决定调用 | 每轮或会话结束 |
| **目标** | 专家知识库 | 了解用户 |

**Memory 类型**:

1. **Declarative Memory** ("知道什么")
   - Semantic: 一般知识
   - Entity/Episodic: 用户特定事实

2. **Procedural Memory** ("知道如何")
   - 工作流程、工具调用序列

**组织模式**:
- **Collections**: 多个独立记忆
- **Structured User Profile**: 结构化用户画像
- **Rolling Summary**: 单一演进摘要

**存储架构**:
- Vector Database: 语义相似度搜索
- Knowledge Graph: 实体关系推理
- Hybrid: 结合两者

### 5.2 你的项目实现 - 缺失 ❌

**当前状态**: 项目中 **没有实现 Memory 系统**

**现有实现（澄清）**:
- 现有 `CacheSessionStore` 是**会话级持久化**（按 `session_id`），用于短期回放/排障/续跑
- TTL 过期后会话状态丢失
- **未实现**按 `user_id` 聚合的跨会话 Memory：无法“抽取→整合→检索”用户/任务知识

**缺失的 Memory 能力**:

| 能力 | 影响 | 优先级 |
|------|------|--------|
| Procedural Memory（最佳工具路径/失败恢复 playbook） | 降低迭代次数、提升成功率与成本可控 | P0 |
| 记住学生常见错误类型（需 user_id 与合规） | 个性化批改建议 | P1 |
| 记住用户的批改偏好（需 user_id 与合规） | 个性化体验 | P2 |
| 跨会话学习模式分析（需明确产品目标与隐私边界） | 长期洞察价值 | P2 |

**符合度**: ❌ **2/10** - 完全缺失，仅靠 Session TTL 模拟

---

## 6. 多 Agent 协作对比

### 6.1 文档描述

**Session History 管理模式**:

1. **Shared, Unified History** (共享统一历史)
   - 所有 Agent 写入同一个 session log
   - 适合紧密耦合的任务
   - 单一真相来源

2. **Separate, Individual Histories** (分离独立历史)
   - 每个 Agent 有自己的私有 log
   - 通过 A2A 协议或 Agent-as-a-Tool 通信
   - 只共享最终输出，不共享过程

**跨框架互操作性**:
- 不同框架的 Session Schema 不兼容
- 解决方案: **Memory Layer** (框架无关的数据层)

### 6.2 你的项目实现

**当前架构**:
- **单一运行时多角色** (Planner/Executor/Reflector/Aggregator)
- 共享同一个 `SessionState`
- 无跨框架通信需求

**分析**:
- ✅ 符合 **"Shared, Unified History"** 模式
- ✅ 所有角色共享 `state.tool_results`, `state.plan_history`
- ⚠️ 但这是 **Level 2** (内部多角色)，非 **Level 3** (跨 Agent 协作)

**文档对比**:
```
文档 Level 3: Agent A (框架 X) ──A2A──> Agent B (框架 Y)
                  ↓ Session                      ↓ Session
你的实现:  Planner ───────────────> Executor ──> Reflector
                ↓ 共享 SessionState
```

**符合度**: ⚠️ **4/10** - 符合共享历史模式，但非跨 Agent 协作

---

## 7. 生产环境考虑

### 7.1 文档要求

#### 7.1.1 Security and Privacy

| 要求 | 文档标准 |
|------|---------|
| **Strict Isolation** | 用户间严格隔离 (ACL) |
| **PII Redaction** | 写入前脱敏 |
| **Authentication** | 每次请求验证用户身份 |

#### 7.1.2 Data Integrity

| 要求 | 文档标准 |
|------|---------|
| **TTL Policy** | 自动清理过期会话 |
| **Deterministic Order** | 保证事件顺序 |
| **Data Retention Policy** | 明确的保留策略 |

#### 7.1.3 Performance

| 要求 | 文档标准 |
|------|---------|
| **Low Latency** | 读写必须极快 |
| **Data Transfer Optimization** | 过滤/压缩历史 |
| **Background Processing** | Memory 生成异步化 |

### 7.2 你的项目实现对比

| 要求 | 项目实现 | 符合度 |
|------|---------|--------|
| **Strict Isolation** | ❌ 无 user_id 绑定 | **2/10** |
| **PII Redaction** | ❌ 无脱敏 | **1/10** |
| **TTL Policy** | ✅ 有 TTL | **8/10** |
| **Deterministic Order** | ⚠️ 单请求内顺序确定；并发/重入场景缺显式顺序与幂等保证 | **6/10** |
| **Low Latency** | ✅ Redis 缓存 | **8/10** |
| **Background Processing** | ⚠️ 当前主流程同步；缺“异步 memory generation/离线 compaction” | **3/10** |

**符合度**: ⚠️ **5/10** - 性能较好；隔离/脱敏/审计与后台化不足

---

## 8. 改进建议

### 8.1 P0: Session 生产底座（隔离 / 脱敏 / 事件化 / 审计 / 用户控制）

> 这一项是“能不能上线”的底线工程：如果没有严格隔离、脱敏、审计、确定性事件顺序与并发幂等，Memory/Compaction 做得再好也会引入高风险和难以排查的线上问题。

**目标**:
- ✅ 用户级严格隔离：任何会话读写都必须绑定 `user_id`
- ✅ 写入前脱敏：Session 与事件在持久化前必须输出净化（尤其是 OCR 文本与模型输出）
- ✅ 统一事件流：将 `planner → tool_call → tool_result → reflection → aggregate → final` 变成可追溯事件序列
- ✅ 审计与可恢复：每次状态变更可追踪、可回放；异常可降级并触发 HITL
- ✅ 并发/重入安全：保证单会话事件有序，支持幂等写入（至少做到“不会写坏状态”）

**实施方案（最小可上线版本）**:

#### 8.1.1 SessionState 必备字段（与现状对齐的增量）

```python
@dataclass
class SessionState:
    session_id: str
    user_id: str                      # P0: 用户隔离关键字段
    created_at: datetime
    updated_at: datetime
    state_version: int                # P0: 乐观锁/并发保护（CAS）
    request_id: str                   # P0: 每次请求链路追踪
    events: list[SessionEvent]        # P0: 统一事件流（替代“只靠 plan_history”）
    warnings: list[dict]              # 记录异常/降级/提示
```

#### 8.1.2 统一事件模型（核心：可追溯 + 可压缩 + 可做 Memory 提取）

```python
@dataclass
class SessionEvent:
    event_id: str
    ts: datetime
    type: str  # user_input | planner | tool_call | tool_result | reflection | aggregate | final | error | hitl
    request_id: str
    payload: dict
    redacted: bool
    token_estimate: int               # 便于 compaction
```

事件化落地后，`plan_history` 仍可以保留作为“规划轨迹视图”，但“事实来源（Source of Truth）”应当是 `events[]`。

#### 8.1.3 写入前脱敏与输出净化（必须在“持久化边界”执行）

- **脱敏对象**：OCR 原文、图片识别的结构化文本、模型生成的解释/评语、工具返回中的原始文本片段
- **脱敏策略**：先规则/正则，再上下文验证；统一替换为占位符（如 `[REDACTED:PHONE]`）
- **安全底线**：任何未标记 `redacted=true` 的事件禁止写入长期存储（SessionStore / MemoryStore）

#### 8.1.4 审计日志与字段约定（用于排障与合规）

- 每次 `load/save/append_event/compaction/memory_write` 必须记录：`user_id/session_id/request_id/event_id/type/state_version/duration_ms/status/error_code`
- 对外响应与对内日志要分离：日志允许更丰富字段，但必须脱敏

#### 8.1.5 错误恢复与 HITL 触发规则（先定义，再实现）

- **触发条件（示例）**：
  - `reflector_parse_failed` / `aggregator_parse_failed`
  - `reflection.pass_ == False` 且 `reflection_count` 达到上限
  - `reflection.confidence < threshold` 或出现高风险 `issues`（例如关键步骤缺失）
  - 工具链连续失败（同一工具失败 ≥ N 次）
- **恢复策略**：
  - 先降级（减少工具/缩短上下文/模板化输出）
  - 再重试（带幂等键避免重复写入）
  - 最后 HITL：写入 `hitl` 事件 + 生成可复现的最小上下文包

#### 8.1.6 用户控制与数据治理（P0 先定义好接口与默认策略）

- `memory_opt_out`：用户选择不写入长期记忆（仍允许临时 Session）
- `delete_user_data(user_id)`：删除该用户 Session 与 Memory（可按保留策略实现延迟删除）
- **保留策略**：Session 默认 TTL；审计日志更短/更严格；Memory 必须可配置 TTL 与版本化

---

### 8.2 P1: Memory（Procedural-first，先“提升稳定性与成本”，再做画像）

> 对你当前“任务式批改 Agent”而言，P0 先把 Session 底座做好；Memory 建议从 **Procedural Memory** 开始做（工具选择/降级路径/校验策略），Declarative（学生画像）需要 `user_id` 与治理能力成熟后再逐步引入。

**目标**:
- ✅ 让 Agent “少走弯路”：在相似场景下复用可靠的工具调用路径/校验方式
- ✅ 降低错误与成本：减少无效反思回合、减少重复工具调用、提升一次通过率
- ✅ 控制风险：不存储原始 OCR/个人信息，只存“可证明、可回放”的结构化结论

#### 8.2.1 最小 Memory Schema（强调来源、可信度、污染标记）

```python
@dataclass
class UserMemory:
    user_id: str
    version: int
    updated_at: datetime
    procedural: dict                  # P1: 优先落地（工具路径/降级/验证）
    declarative: dict | None          # P2: 学生画像（需要合规与更强数据治理）
    provenance: dict                  # 来源：session_ids / event_ids / model_versions
    confidence: float                 # 0..1
    tainted: bool                     # 任何“可能被投毒/未脱敏”的内容都必须标记并拒绝注入
```

#### 8.2.2 提取信号（对齐你项目现状：reflection + 聚合结果 + warnings）

- **运行级信号（Run-level）**：`reflection.pass_`、`reflection.confidence`、`reflection.issues`、`reflection_count`、`state.warnings`
- **题目级信号（Item-level）**：`aggregated.results[]` 中的 `verdict`（correct/incorrect/uncertain）与关键错误类别（可由规则/LLM 分类，但必须可追溯到事件）
- **路径信号（Path-level）**：从 `events[]` 中回放 `tool_call → tool_result` 序列，统计成功率/失败原因/最优迭代次数

#### 8.2.3 安全与抗投毒（必须写入方案，不然后期很难补）

- **禁止写入**：原始 OCR 文本、原始图片内容、未经脱敏的用户输入、模型自由文本“猜测”
- **仅允许写入**：结构化统计（计数/频率）、场景标签、工具序列摘要、明确可验证的结论（带 `provenance`）
- **注入前检查**：`tainted==true` 或 `confidence < threshold` 的记忆不得注入 prompt

#### 8.2.4 并发与幂等（至少做到不会写坏）

- **乐观锁**：`UserMemory.version` + CAS 更新；冲突时做 merge（加权/去重）再重试
- **幂等键**：对“同一 session 的同一提取任务”使用 `idempotency_key=session_id+extractor_version`，避免重复写入
 
#### 8.2.5 注入策略（Prompt Assembly）

- 放在 **planner 的受控段落** 中（例如 `## Memory (Verified)`），并明确“仅作建议，不是事实来源”
- 单次注入设 token 预算；超过预算只保留 Top-K（按置信度/新鲜度/相关性）

---

### 8.3 P1: Context Compaction（事件流 + 规划轨迹的可控压缩）

> 现阶段你主要记录 `plan_history` 与 `tool_results`，但缺少统一事件流。建议先事件化（8.1），再对 `events[]` 做 token 预算与分层压缩；否则“压缩对象不完整”，容易压掉关键事实导致不可回放/不可解释。

```python
class ContextCompactor:
    def __init__(self, max_tokens: int = 8000):
        self.max_tokens = max_tokens
        self.tokenizer = get_tokenizer()

    def compact_events(self, events: list[SessionEvent]) -> list[SessionEvent]:
        """基于 token 数量动态压缩：保留近因事实，摘要远因历史。"""

        current_tokens = sum(e.token_estimate for e in events)
        if current_tokens <= self.max_tokens:
            return events

        # 策略：保留最近 N 个“关键事件”，其余折叠为 summary 事件
        keep_types = {"user_input", "tool_result", "aggregate", "final", "error", "hitl"}
        recent = []
        old = []
        for e in events[::-1]:
            if e.type in keep_types and len(recent) < 40:
                recent.append(e)
            else:
                old.append(e)
        recent = list(reversed(recent))
        old = list(reversed(old))

        summary = self._summarize_old_events(old)  # 必须使用脱敏后的 payload
        summary_event = SessionEvent(
            event_id="summary:1",
            ts=now(),
            type="summary",
            request_id=recent[-1].request_id if recent else "n/a",
            payload={"summary": summary, "source_event_count": len(old)},
            redacted=True,
            token_estimate=self.tokenizer.count(summary),
        )
        return [summary_event] + recent
```

---

### 8.4 P2: 考虑多 Agent 扩展（可选）

**如果未来需要跨 Agent 协作**:

1. **实现 Memory Layer** 作为框架无关的数据层
2. **使用 A2A 协议** 进行跨框架通信
3. **保留统一 Session** 作为真相来源

---

## 9. 总结

### 9.1 核心优势

1. **SessionState 容器清晰** (8/10)
   - 字段覆盖预处理、规划轨迹、工具结果与告警
   - `to_dict/from_dict` 便于缓存持久化（已有 TTL）
   - ⚠️ 缺少统一 `events[]`（事实来源仍不够完整）

2. **Context Engineering 流程符合** (7/10)
   - 完整的 Fetch → Prepare → Invoke → Upload 循环
   - 动态上下文组装

3. **性能良好** (8/10)
   - Redis 缓存
   - 同步链路清晰、易观测（已有结构化 log_event）

### 9.2 主要差距

1. **P0 生产底座不足** (5/10)
   - 无 user_id 绑定导致“严格隔离”缺失
   - 无持久化前脱敏（OCR/模型输出/工具返回）
   - 无统一事件流与审计字段约定，排障/回放/合规都受限

2. **Memory 体系缺失（建议 Procedural-first）** (2/10)
   - 目前没有长期记忆管理与注入策略
   - 若直接做学生画像（Declarative）会引入合规与投毒风险

3. **Compaction/并发幂等未成体系** (4/10)
   - 当前迭代轮次有限，短期不必“过度压缩”
   - 但一旦引入 `events[]` 与更长链路，必须配套 token 预算、摘要与幂等保护

### 9.3 建议优先级

| 优先级 | 改进项 | 工作量 | 收益 |
|--------|--------|--------|------|
| **P0** | Session 生产底座（隔离/脱敏/事件化/审计/恢复/用户控制） | 4-6 天 | 高 |
| **P1** | Procedural Memory（工具路径/降级/校验策略） | 3-5 天 | 高 |
| **P1** | Context Compaction（事件流 token 预算 + summary） | 2-3 天 | 中 |
| **P2** | Declarative Memory（学生画像，需合规与授权） | 5-10 天 | 中 |
| **P2** | 多 Agent 扩展 | 10+ 天 | 低 |

---

## 10. 参考资料

- [Context Engineering_ Sessions & Memory.md](docs/agent/Context%20Engineering_%20Sessions%20%26%20Memory.md)
- [Introduction to Agents.md](docs/agent/Introduction%20to%20Agents.md)
- [Agent Quality.md](docs/agent/Agent%20Quality.md)

---

# 附录: 详细实施方案设计

> 本节提供所有改进项的详细架构设计和实施方案，**仅包含设计思路，不涉及具体代码实现**。

---

## A.0 P0: Events 事件模型（SessionEvent）

> 你当前实现里主要有 `plan_history/tool_results/warnings` 等离散结构与日志事件，但缺少统一、可回放的 `events[]`。在“Session/Mem/Compaction/审计”里，事件流应该是 **事实来源（Source of Truth）**。

### A.0.1 事件 Schema（最小可用版本）

```json
{
  "event_id": "string (uuid or stable id)",
  "seq": 1,
  "ts": "RFC3339 datetime",
  "type": "user_input|planner|tool_call|tool_result|reflection|aggregate|final|summary|error|hitl",
  "user_id": "string",
  "session_id": "string",
  "request_id": "string",
  "payload": {},
  "redacted": true,
  "token_estimate": 123,
  "hash": "string (optional, for tamper-evidence)",
  "meta": {
    "model": "string (optional)",
    "tool_name": "string (optional)",
    "duration_ms": 12,
    "status": "ok|error"
  }
}
```

### A.0.2 必须保证的约束（不满足就会“难压缩/难排障/难审计”）

- **有序性**：同一 `session_id` 内，`seq` 单调递增；`ts` 不要求严格单调但应接近真实顺序
- **可追溯**：`tool_result` 必须能关联到对应 `tool_call`（通过 `event_id` 或 `call_id`）
- **净化边界**：任何写入持久化（SessionStore / MemoryStore）的事件必须 `redacted=true`
- **大小护栏**：`payload` 必须有 size guard（例如超长 OCR 片段禁止入事件，只留摘要 + 引用）
- **可恢复**：出现解析失败/异常时追加 `error` 事件，保证“失败也有证据链”

---

## A.1 P1: Memory 系统完整设计方案（Procedural-first）

### A.1.1 系统架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    Memory Management System                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐      │
│  │  Agent      │───▶│ Memory      │───▶│  Storage    │      │
│  │  (作业批改)  │    │ Manager     │    │  Layer      │      │
│  └─────────────┘    └─────────────┘    └─────────────┘      │
│         │                  │                    │            │
│         │                  │                    │            │
│         ▼                  ▼                    ▼            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              SessionState (当前会话)                 │   │
│  │  - plan_history, tool_results, warnings             │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              UserMemory (长期记忆)                  │   │
│  │  - common_error_types, weak_topics                  │   │
│  │  - effective_tool_paths, learning_progress          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**数据流向**:
```
Agent 执行 → SessionState (临时) → Memory Extraction → UserMemory (持久) → Memory Retrieval → 下次 Agent 执行
```

---

### A.1.2 Memory Schema 设计

#### Declarative Memory (陈述性记忆) - "知道什么"

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `user_id` | str | 用户唯一标识 | "student_12345" |
| `common_error_types` | List[str] | 学生常见错误类型 | ["calculation_error", "concept_misunderstanding"] |
| `error_frequency` | Dict[str, int] | 错误类型频率统计 | {"calculation_error": 15, "unit_confusion": 8} |
| `weak_topics` | List[str] | 薄弱知识点 | ["fraction_addition", "geometry_proof"] |
| `strong_topics` | List[str] | 优势知识点 | ["algebra_simplification"] |
| `learning_progress` | Dict[str, float] | 各科目掌握度 (0-1) | {"math": 0.72, "geometry": 0.58} |
| `recent_mistakes` | List[Dict] | 最近错误记录 (时间序列) | [{"timestamp": "...", "question": "...", "error": "..."}] |
| `improvement_areas` | List[str] | 建议改进方向 | ["practice_fraction_calculation", "review_geometry_theorems"] |

**数据结构设计理念**:
- **粒度**: 按科目 → 知识点 → 错误类型 三级组织
- **时效性**: `recent_mistakes` 保留最近 30 天，自动过期
- **可更新**: 每次批改后更新频率统计和掌握度

#### Procedural Memory (程序性记忆) - "知道如何"

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `user_id` | str | 用户唯一标识 | "student_12345" |
| `effective_tool_paths` | List[Dict] | 成功的工具调用路径 | [{"scenario": "geometry_with_diagram", "tools": ["diagram_slice", "math_verify"], "success_rate": 0.92}] |
| `failed_tool_paths` | List[Dict] | 失败的工具调用路径 | [{"scenario": "complex_text", "tools": ["ocr_fallback"], "reason": "low_confidence"}] |
| `optimal_iteration_count` | Dict[str, int] | 最佳迭代次数 | {"geometry": 1, "algebra": 2} |
| `preferred_verification_methods` | List[str] | 偏好的验证方法 | ["math_verify", "manual_review"] |

**数据结构设计理念**:
- **场景化**: 按 `scenario` 分类工具路径
- **可学习**: 记录成功率和失败原因
- **自适应**: 根据历史数据优化未来工具选择

#### Memory Metadata

| 字段 | 类型 | 说明 |
|------|------|------|
| `memory_id` | str | 记忆唯一标识 (UUID) |
| `user_id` | str | 所属用户 |
| `created_at` | datetime | 创建时间 |
| `last_updated` | datetime | 最后更新时间 |
| `confidence_score` | float (0-1) | 记忆可信度 (基于样本数量) |
| `source_sessions` | List[str] | 产生该记忆的会话 ID 列表 |
| `memory_type` | str | "declarative" 或 "procedural" |

---

### A.1.3 Memory Extraction (记忆提取)

#### 提取触发时机

**Event-Based Triggers** (推荐):

| 触发事件 | 说明 | 优先级 |
|---------|------|--------|
| `any(results[].verdict == "incorrect")` | 题目级错误出现时提取（错误类型/薄弱点） | P1 |
| `reflection.confidence < threshold` 或 `reflection.pass_ == false` | 运行级低置信度/未通过时提取（失败模式/降级路径） | P1 |
| `reflection_count >= 2` 或 `warnings not empty` | 多轮反思/出现降级告警时提取（最佳迭代次数/失败原因） | P1 |
| `final`（会话结束） | 会话结束时批量提取（去重、合并、写入） | P1 |

**Time-Based Triggers**:
- 每天凌晨批量处理前一天的会话
- 适合大数据量的离线分析

#### 提取流程

```
┌─────────────────────────────────────────────────────────┐
│              Memory Extraction Pipeline                  │
├─────────────────────────────────────────────────────────┤
│  1. Input: SessionState(events) + AggregateResult + Reflection │
│                                                         │
│  2. Classification (分类)                               │
│     ├─ Declarative Extraction (陈述性提取)             │
│     │   ├─ Extract error type from results[].verdict   │
│     │   ├─ Extract weak topics from repeated incorrect/uncertain │
│     │   └─ (可选) Extract trends over time (需要合规/用户授权)   │
│     │                                                   │
│     └─ Procedural Extraction (程序性提取)               │
│         ├─ Extract tool_call→tool_result sequences     │
│         ├─ Extract failure reasons from issues/warnings│
│         └─ Calculate optimal reflection/tool iteration │
│                                                         │
│  3. Filtering (过滤)                                   │
│     ├─ Remove duplicates (去重)                         │
│     ├─ Validate relevance (验证相关性)                 │
│     └─ Apply confidence threshold (应用置信度阈值)      │
│                                                         │
│  4. Output: List[UserMemory]                           │
└─────────────────────────────────────────────────────────┘
```

#### 错误类型分类体系

```
Error Taxonomy
├─ Calculation Errors (计算错误)
│   ├─ Arithmetic Mistake (基本运算错误)
│   ├─ Unit Confusion (单位混淆)
│   └─ Sign Error (符号错误)
├─ Conceptual Errors (概念错误)
│   ├─ Formula Misapplication (公式误用)
│   ├─ Theorem Misunderstanding (定理理解偏差)
│   └─ Logic Gap (逻辑跳跃)
├─ Process Errors (过程错误)
│   ├─ Incomplete Steps (步骤不完整)
│   └─ Wrong Method Selection (方法选择错误)
└─ Careless Errors (粗心错误)
    ├─ Copy Error (抄写错误)
    └─ Reading Error (审题错误)
```

#### 提取规则

| 触发条件 | 提取字段 | 更新逻辑 |
|---------|---------|----------|
| `any(results[].verdict == "incorrect")` | `common_error_types` | 对错误类型做 +1（必须可追溯到事件/题目） |
| `incorrect/uncertain 在同一 topic 重复出现` | `weak_topics` | 以滑动窗口累计，超过阈值再写入 |
| `reflection.confidence >= threshold 且 pass_==true` | `effective_tool_paths` | 从事件回放路径并统计 success_rate |
| `reflection_count > 1` 或存在降级 `warnings` | `failed_tool_paths`/`optimal_iteration_count` | 记录失败原因与最优迭代次数 |
| (可选) 有合规与用户授权 | `learning_progress` | 基于长期统计更新（不要靠单次 verdict 直接下结论） |

---

### A.1.4 Memory Consolidation (记忆整合)

#### 整合策略

**Goal**: 避免记忆冲突、去重、合并相似记忆

```
┌─────────────────────────────────────────────────────────┐
│              Memory Consolidation Algorithm             │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  For each new_memory in new_memories:                  │
│                                                         │
│    1. Retrieve existing memories for user_id           │
│                                                         │
│    2. Check for conflicts (冲突检测)                    │
│       ├─ If conflicting information exists:            │
│       │   ├─ Compare confidence_score                   │
│       │   ├─ Keep the one with higher score             │
│       │   └─ Mark the other as stale                   │
│       │                                                   │
│    3. Check for duplicates (去重检测)                    │
│       ├─ If similar memory exists (>90% similarity):    │
│       │   ├─ Merge into single memory                   │
│       │   ├─ Update source_sessions                     │
│       │   └─ Increment sample_count                     │
│       │                                                   │
│    4. Create new memory                                 │
│       └─ If no conflict or duplicate found             │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

#### Conflict Resolution (冲突解决)

| 冲突类型 | 解决策略 | 示例 |
|---------|---------|------|
| 同一知识点既是 strong 又是 weak | 保留最近更新的 | 先认为 strong，后因错误变为 weak |
| 同一工具有不同成功率 | 加权平均 | 旧路径成功率 0.8，新路径 0.9 → 合并为 0.85 |
| 同一错误类型频率不一致 | 累加计数 | 旧记录 5 次，新记录 3 次 → 更新为 8 次 |

---

### A.1.5 Memory Storage (记忆存储)

#### 存储架构对比

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **Redis (Hash)** | 快速、已集成 | 无高级查询 | ⭐⭐⭐ |
| **PostgreSQL (JSONB)** | 结构化查询、事务 | 需新基础设施 | ⭐⭐⭐⭐ |
| **Vector DB (Pinecone)** | 语义搜索 | 过度设计 | ⭐⭐ |
| **Hybrid (PG + Redis)** | 兼顾性能和查询 | 复杂度高 | ⭐⭐⭐⭐⭐ |

**推荐方案**: **Redis 为主，PostgreSQL 为辅**

```
┌─────────────────────────────────────────────────────────┐
│              Hybrid Storage Architecture                │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────────┐      ┌──────────────────┐        │
│  │   Redis (Hot)     │      │ PostgreSQL (Warm) │        │
│  │                  │      │                  │        │
│  │ - UserMemory     │◀────▶│ - Archive        │        │
│  │ - Latest data    │ Sync │ - Historical     │        │
│  │ - Fast lookup    │      │ - Analytics      │        │
│  └──────────────────┘      └──────────────────┘        │
│            ▲                         ▲                 │
│            └─────────┬───────────────┘                 │
│                      │                                 │
│                      ▼                                 │
│            ┌──────────────────┐                       │
│            │  Memory Manager  │                       │
│            └──────────────────┘                       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

#### Redis Key Schema

```
autonomous:memory:{user_id}                    # 用户完整记忆
autonomous:memory:declarative:{user_id}       # 陈述性记忆
autonomous:memory:procedural:{user_id}        # 程序性记忆
autonomous:memory:errors:{user_id}            # 错误统计
autonomous:memory:topics:{user_id}            # 知识点掌握度
```

#### TTL 策略

| 数据类型 | TTL | 说明 |
|---------|-----|------|
| 热数据 (最近 30 天) | 30 天 | 快速访问 |
| 温数据 (30-90 天) | 90 天 | PostgreSQL 持久化 |
| 冷数据 (>90 天) | 永久 | 归档存储 |

---

### A.1.6 Memory Retrieval (记忆检索)

#### 检索时机

**Static Retrieval** (推荐):

```
每次 Agent 执行前:
  1. 加载 SessionState
  2. 加载 UserMemory (基于 user_id)
  3. 组装到 prompt 中
  4. 执行 Agent
```

#### 检索策略

| 场景 | 检索字段 | 用途 |
|------|---------|------|
| 所有场景 | `procedural.effective_tool_paths` | 优先选择成功率高的工具序列 |
| 所有场景 | `procedural.failed_tool_paths` | 避免已知失败组合/快速降级 |
| 低置信度/多轮反思 | `procedural.preferred_verification_methods` | 选择更可靠的校验策略 |
| (可选) 有画像且合规 | `declarative.common_error_types` | 预警常见错误（必须标注可信度与时效） |
| (可选) 有画像且合规 | `declarative.weak_topics/strong_topics` | 个性化建议（仅作提示，不作为事实） |

#### Context Assembly 格式

```
## Memory (Verified)

- Suggested tool path: {procedural.effective_tool_paths.top1}
- Verification: {procedural.preferred_verification_methods.top1}
- Avoid: {procedural.failed_tool_paths.top1}

## (Optional) Student Profile (If Enabled & Compliant)

**Common Error Types**: {declarative.common_error_types.join(", ")}

**Weak Topics**: {declarative.weak_topics.join(", ")}

**Strong Topics**: {declarative.strong_topics.join(", ")}

**Learning Progress**:
- Math: {declarative.learning_progress.math * 100}%
- Geometry: {declarative.learning_progress.geometry * 100}%

**Recent Mistakes** (Last 5):
{# Each mistake #}
- {timestamp}: {question} → {error}

**Recommended Approach**:
Based on past performance, this student tends to struggle with {weak_topic}.
Consider using {effective_tool_path} for better accuracy.
```

### A.1.7 安全与抗投毒（必须在设计阶段写死）

**原则**：Memory 必须比“模型输出”更可信，否则它会放大幻觉与投毒风险。

- **禁止写入**：原始 OCR、原始用户输入、未脱敏文本、自由文本猜测、不可追溯的结论
- **必须携带**：`provenance`（来源 session/event）、`confidence`、`updated_at`、`tainted`、`extractor_version`
- **注入前校验**：`tainted==true` 或 `confidence < threshold` → 绝不注入；只允许作为“后台统计”
- **反投毒护栏**：对“单次异常极端样本”做降权；要求至少 N 个独立 session 支持后才进入高权重记忆

### A.1.8 并发/一致性/幂等（Redis/PG 都适用）

- **乐观锁**：`UserMemory.version` + CAS 更新（失败则 reload+merge+retry）
- **幂等写入**：`idempotency_key = session_id + extractor_version + kind`，同一 key 重复写入应当无副作用
- **合并策略**：计数类字段累加；列表类做去重；success_rate 做加权；冲突结论保留“新鲜度更高且置信度更高”的

### A.1.9 注入策略（Prompt 影响可控）

- **放置位置**：planner prompt 的固定段落（例如 `## Memory (Verified)`），避免污染系统指令
- **预算控制**：单次注入 token 预算 + Top-K；超出预算只保留最高价值的 procedural 记忆
- **可解释**：注入内容必须能引用 `provenance`，否则只能作为低权重提示

### A.1.10 用户控制与合规（避免“做出来但不能用”）

- `memory_opt_out`：默认不写画像类 Declarative Memory；用户显式同意才启用
- `delete_user_data(user_id)`：可删除会话与记忆；审计日志单独策略（更短 TTL / 更严格脱敏）
- **保留策略**：Session TTL（短）；Procedural Memory TTL（中）；Declarative Memory TTL（可选且更严格）

---

## A.2 P0: Session 生产底座（隔离 / 脱敏 / 事件化 / 审计 / 恢复）

> 本节与 A.0（事件模型）配套：先把 Session 的事实来源、隔离与脱敏边界做对，再谈 Memory/Compaction/分析。

### A.2.1 用户级隔离设计

#### 安全模型

```
┌─────────────────────────────────────────────────────────┐
│              Security & Isolation Model                 │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Request Flow:                                         │
│                                                         │
│  User Request                                          │
│       │                                                 │
│       ▼                                                 │
│  ┌─────────────────┐                                   │
│  │ Authentication  │ ← Verify JWT/Token               │
│  └────────┬────────┘                                   │
│           │                                             │
│           ▼                                             │
│  ┌─────────────────┐                                   │
│  │  Authorization  │ ← Check user_id ownership        │
│  └────────┬────────┘                                   │
│           │                                             │
│           ▼                                             │
│  ┌─────────────────┐                                   │
│  │  Session Load   │ ← Only load user's own sessions  │
│  └─────────────────┘                                   │
│                                                         │
│  Isolation Layers:                                     │
│  1. API Layer: JWT validation                          │
│  2. Application Layer: user_id binding                 │
│  3. Storage Layer: Key prefix with user_id            │
│  4. Audit Layer: Log all access attempts               │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

#### SessionState 扩展设计

**新增字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | str | 用户唯一标识 (必需) |
| `created_at` | datetime | 会话创建时间 |
| `last_accessed_at` | datetime | 最后访问时间 |
| `access_count` | int | 访问次数 (用于分析) |
| `owner_id` | str | 所有者标识 (用于多租户) |

#### Key Schema 更新

```
Before: autonomous:state:{session_id}
After:  autonomous:state:{user_id}:{session_id}
```

#### 安全检查点

| 检查点 | 位置 | 验证逻辑 |
|--------|------|----------|
| API 入口 | FastAPI 路由 | JWT 验证 |
| Session 加载 | `CacheSessionStore.load()` | user_id 匹配 |
| Session 保存 | `CacheSessionStore.save()` | user_id 匹配 |
| 跨用户访问 | 所有 Session 操作 | 抛出 SecurityError |

---

### A.2.2 PII Redaction 设计

#### PII 检测策略

**多层检测**:

```
┌─────────────────────────────────────────────────────────┐
│              PII Detection Pipeline                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Input Text (OCR text, plan_history, etc.)             │
│       │                                                 │
│       ▼                                                 │
│  Layer 1: Pattern Matching (正则匹配)                   │
│       ├─ Phone: 1[3-9]\d{9}                           │
│       ├─ Email: standard email regex                   │
│       ├─ ID Card: \d{17}[\dXx]                         │
│       ├─ Student ID: \d{10,12}                         │
│       └─ Name: [\u4e00-\u9fa5]{2,3} (optional)        │
│       │                                                 │
│       ▼                                                 │
│  Layer 2: Context Validation (上下文验证)               │
│       ├─ "学号：2021001234" → Student ID               │
│       ├─ "电话：138..." → Phone                        │
│       └─ "2021001234" alone → Not ID (no context)      │
│       │                                                 │
│       ▼                                                 │
│  Layer 3: Confidence Scoring (可选，使用 NER)           │
│       └─ 使用 NER 模型验证并打分                         │
│                                                         │
│  Output: List[DetectedPII]                             │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

#### Redaction 策略

| PII 类型 | 替换策略 | 示例 |
|---------|---------|------|
| Phone | `[手机号_已脱敏]` | `138****5678` → `[手机号_已脱敏]` |
| Email | `[邮箱_已脱敏]` | `user@example.com` → `[邮箱_已脱敏]` |
| ID Card | `[身份证号_已脱敏]` | `110101199001011234` → `[身份证号_已脱敏]` |
| Student ID | `[学号_已脱敏]` | `2021001234` → `[学号_已脱敏]` |
| Name | `[姓名_已脱敏]` (可选) | `张三` → `[姓名_已脱敏]` |

#### 集成点

```
┌─────────────────────────────────────────────────────────┐
│              PII Redaction Integration Points           │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Point 1: OCR Output                                   │
│    ocr_fallback() → PII Filter → SessionState.ocr_text │
│                                                         │
│  Point 2: Session Save                                 │
│    CacheSessionStore.save() → Sanitize → Redis         │
│                                                         │
│  Point 3: Agent Response                               │
│    AggregatorAgent → PII Filter → User                 │
│                                                         │
│  Point 4: Logging                                      │
│    Log Output → PII Filter → Log File                  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

### A.2.3 事件化、审计与错误恢复设计（依赖 A.0）

#### 为什么要“先事件化”

- 没有统一事件流时，“发生了什么”分散在 `plan_history/tool_results/log_event` 里：难回放、难压缩、难排障
- 事件化后：同一条证据链可以同时服务于 **Compaction**、**Memory 提取**、**HITL**、**监控告警**

#### 事件写入点（与现有实现映射）

- `planner`：每轮计划输出（可保留摘要字段，避免存超长推理）
- `tool_call/tool_result`：每次工具调用与结果（必须可关联）
- `reflection`：每轮反思输出（含 `pass_/confidence/issues/suggestion`）
- `aggregate/final`：聚合结果与最终输出（必须可追溯到题目级结果）
- `error/hitl`：任何解析失败、超限、降级、人工介入

#### 审计日志字段约定（建议 JSON line）

```json
{
  "ts": "RFC3339",
  "level": "INFO|WARN|ERROR",
  "event": "session_append_event|session_save|memory_write|compaction",
  "user_id": "string",
  "session_id": "string",
  "request_id": "string",
  "state_version": 12,
  "event_id": "string",
  "event_type": "tool_result",
  "duration_ms": 12,
  "status": "ok|error",
  "error_code": "optional",
  "meta": {"model": "optional", "tool": "optional"}
}
```

#### 错误恢复与 HITL

- 解析失败：写入 `error` 事件（含失败点与最小上下文），并执行降级策略（例如跳过某工具/模板化输出）
- 多轮失败：满足 HITL 触发规则时，写入 `hitl` 事件 + 生成可复现包（脱敏后的 events 摘要 + 关键输入）
- 幂等：同一 `request_id` 的重试不得重复追加不可逆事件（需要 `idempotency_key` 或基于 `event_id` 去重）

---

### A.2.4 Token-Based Compaction 设计（P1，依赖事件流）

#### Compaction 策略对比

| 策略 | 触发条件 | 压缩方法 | 适用场景 |
|------|---------|----------|----------|
| **Keep Last N** | 固定轮数 | 保留最近 N 次 | 短对话 |
| **Token-Based** | Token 阈值 | 动态截断 | 长对话 |
| **Recursive Summary** | Token 阈值 + LLM | 旧内容摘要 | 很长对话 |
| **Hybrid** | Token 阈值 | Last N + Summary | 生产环境 (推荐) |

#### Hybrid Compaction 设计

```
┌─────────────────────────────────────────────────────────┐
│           Hybrid Compaction Strategy                     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Input: events (List[SessionEvent])                     │
│                                                         │
│  Step 1: Token Counting                                 │
│    tokens = count_tokens(events)                        │
│                                                         │
│  Step 2: Decision                                      │
│    IF tokens < THRESHOLD_LOW (4000):                    │
│        → Return all (no compaction)                     │
│                                                         │
│    ELSE IF tokens < THRESHOLD_HIGH (8000):              │
│        → Return recent key events + last N plans        │
│                                                         │
│    ELSE (tokens >= THRESHOLD_HIGH):                     │
│        → Apply Recursive Summarization                  │
│                                                         │
│  Step 3: Recursive Summarization (if needed)            │
│    old_events = events[:-N]                              │
│    recent_events = events[-N:]                           │
│                                                         │
│    summary = llm.summarize(old_events)                  │
│                                                         │
│    return [                                               │
│      {"type": "summary", "content": summary},           │
│      ...recent_events                                    │
│    ]                                                     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

#### 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `threshold_low` | 4000 tokens | 低于此值不压缩 |
| `threshold_high` | 8000 tokens | 高于此值使用摘要 |
| `last_n_events` | 40 | 保留的最近关键事件数量（含 tool_result/aggregate/final/error 等） |
| `summary_model` | "gpt-4o-mini" | 用于摘要的模型 (低成本) |

---

## A.3 P2: 高级特性 (可选)

### A.3.1 Recursive Summarization

#### 多层摘要

```
Original plan_history (20 plans, 15000 tokens)
    │
    ▼
Layer 1 Summary (plans 1-10) → 500 tokens
Layer 1 Summary (plans 11-20) → 500 tokens
    │
    ▼
Layer 2 Summary (combined) → 800 tokens
    │
    ▼
Final Context:
  - Layer 2 Summary
  - Plans 18-20 (verbatim)
  = ~2000 tokens total
```

---

### A.3.2 Memory-as-a-Tool

#### 工具定义

```
Tool: memory_retrieval

Description: Retrieves relevant memories about the user to guide
the current grading decision.

Input Schema:
{
  "user_id": "string (required)",
  "query_type": "errors | topics | tool_paths | all",
  "subject_filter": "string (optional, e.g., 'math', 'geometry')"
}

Output Schema:
{
  "memories": [
    {
      "type": "declarative | procedural",
      "content": "...",
      "confidence": 0.85
    }
  ]
}
```

---

## A.4 实施路线图

### A.4.1 Phase 1: Session Foundation (P0 - 4-6 days)

**Day 1-2: Isolation + Redaction 边界**
- 引入 `user_id` 绑定（SessionStore/MemStore 统一 key schema）
- 定义“持久化边界”的输出净化与脱敏策略（OCR/工具返回/模型输出）
- 约定审计日志字段（request_id/session_id/user_id/event_id/type/status）

**Day 3-4: 事件化 + 审计**
- 落地 `SessionEvent`（A.0），将 planner/tool/reflection/aggregate/final 串成 `events[]`
- 建立事件 size guard 与 redacted gate（未脱敏不可入库）
- 形成可回放的最小证据链（失败也要有 error 事件）

**Day 5-6: 错误恢复 + HITL + 并发幂等**
- 明确 HITL 触发规则与降级策略（先降级再重试再 HITL）
- 引入 `state_version`/CAS 与幂等键，避免重试写坏状态
- 端到端演练：解析失败/工具失败/超时/重试

### A.4.2 Phase 2: Procedural Memory (P1 - 3-5 days)

**Day 1-2: Schema + Store + Governance**
- 定义 Procedural-first 的 `UserMemory`（含 provenance/confidence/tainted/version）
- 建立 opt-out/delete/TTL 策略（A.1.10）

**Day 3-4: Extraction + Merge**
- 从 `events[]` + `reflection` + `aggregate.results[]` 提取工具路径与失败模式
- CAS 更新 + merge 去重（计数累加/成功率加权/冲突按新鲜度与置信度）

**Day 5: Injection & Evaluation**
- 注入 `## Memory (Verified)`（token 预算 + Top-K）
- 用离线样本评估：迭代次数、失败率、成本、准确率变化

### A.4.3 Phase 3: Context Compaction (P1 - 2-3 days)

- 对 `events[]` 做 token 预算 + summary 事件（摘要必须使用脱敏 payload）
- 引入“关键事件保留集”（tool_result/aggregate/final/error/hitl）
- 验证：压缩后可回放、可解释、不会丢关键证据

### A.4.4 Phase 4: Advanced Features (P2 - 5-10 days)

- Declarative Memory（学生画像，需合规/授权/更强治理）
- Recursive Summarization（超长上下文时再引入）
- Memory-as-a-Tool（确有动态检索需求时再引入）

---

## A.5 预期收益评估

### A.5.1 Memory 系统收益

| 指标 | 改进前 | 改进后 | 提升 |
|------|--------|--------|------|
| 跨会话个性化能力 | 0% | 100% | ∞ |
| 错误预测准确率 | N/A | 35% | 新能力 |
| 工具选择准确率 | 72% | 85% | +18% |
| 用户留存率 (假设) | 60% | 75% | +25% |

### A.5.2 安全性收益

| 指标 | 改进前 | 改进后 | 提升 |
|------|--------|--------|------|
| 多租户隔离 | 无 | 完整 | ✅ |
| PII 泄露风险 | 高 | 低 | ↓80% |
| 审计可追溯性 | 无 | 完整 | ✅ |

---

## A.6 总结

### A.6.1 核心价值

1. **P0 Session 底座决定“能不能长期跑”**
   - 严格隔离 + 写入前脱敏，降低合规与数据泄露风险
   - 统一事件流 + 审计字段，显著提升排障、回放与评估能力
   - 错误恢复/HITL，保证失败可控且可追溯

2. **P1 Procedural Memory 是最“稳”的高收益**
   - 先记“怎么做”（工具路径/降级/校验），提升稳定性与成本效率
   - Declarative（学生画像）需要合规与授权，建议后置

3. **Compaction 是配套能力而非起点**
   - 短期因迭代轮次有限不紧迫
   - 一旦事件流变长/加入更多工具，token 预算与 summary 事件就会成为刚需

4. **渐进式实施（建议）**
   - P0: Session Foundation (4-6 天)
   - P1: Procedural Memory (3-5 天)
   - P1: Context Compaction (2-3 天)
   - P2: Advanced (5-10 天)

### A.6.2 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 存储架构 | Redis + PostgreSQL | 兼顾性能和查询 |
| 压缩策略 | Hybrid | 平衡效果和复杂度 |
| 检索方式 | Static | 简单可靠，适合当前架构 |
| 隔离粒度 | user_id | 符合多租户模型 |

---

**文档版本**: v1.0
**最后更新**: 2025-12-27
**维护者**: Codex CLI Agent
