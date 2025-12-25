## 自主阅卷 Agent 结构设计（ADK 对齐版）

本设计参考 Agent Development Kit (ADK) 的核心概念与模式：
- LLM Agent：作为“思考与决策”的核心（参考 ADK LlmAgent 说明）
- Workflow Agents：用顺序/循环编排子代理执行流（Sequential/Loop Agent）
- Function Tools：统一工具调用接口（Function tools）
- Memory：会话级状态（Session Memory）
- Streaming Tools：流式/分段输出
- Observability：日志与追踪（Logging）

> 注：对齐 ADK 的结构与范式，但不依赖 Google 服务实现。

---

### 1. 目标与原则

**目标**
- 让 Agent 拥有自主性：目标拆解、规划、调用工具、根据反馈调整方案并评估结果。
- 让批改“基于视觉理解”而非纯 OCR 推断。
- 在用户界面中呈现：识别原文 + 判断依据 + 批改结果，且判断依据为中文自然语言。

**最小护栏**
- 必须输出结构化结果（判定 + judgment_basis）
- judgment_basis 必须包含判断依据（中文）
- 非作业图拒绝并返回明确理由

**不做**
- 不强制“截线/被截线”术语（仅在题干明确涉及时建议使用）
- 不做成本节约策略（不保留 OCR 快速通道）

---

### 2. ADK 风格架构拆解

#### 2.1 Agent 角色与职责

**A. PlannerAgent（LLM Agent）**
- 输入：用户图片、题目上下文
- 责任：形成“执行计划”
  - 是否需要切片补齐
  - 是否需要数学工具验证
  - 是否需要反思/二次判断

**B. ExecutorAgent（Workflow Agent / Sequential）**
- 负责按计划调用工具，并将结果回传给 Planner

**C. ReflectorAgent（LLM Agent）**
- 对当前证据进行一致性校验
- 如发现证据不足/自相矛盾，触发 Loop 迭代

**D. AggregatorAgent（LLM Agent）**
- 生成最终结构化 JSON：
  - ocr_text（识别原文）
  - results（全题判定）
  - judgment_basis（中文依据）
  - summary / warnings

> 实现方式：Planner + Reflector 可以通过 LoopAgent 串联，确保“计划→执行→反思→再计划”的闭环。

#### 2.2 工作流（Workflow Agents）

**SequentialAgent（顺序执行）**
1) PlannerAgent（生成执行计划）
2) ExecutorAgent（执行工具）
3) ReflectorAgent（自检/纠错）
4) AggregatorAgent（输出结果）

**LoopAgent（迭代执行）**
- 当 Reflector 判定“证据不足/矛盾”时：
  - 再次调用 Planner → 工具 → Reflector
- 终止条件：
  - 达到置信阈值或证据充分
  - 达到最大迭代次数

---

### 3. Tooling（Function Tools 对齐）

**固定前置流水线（非 Agent 决策）**
- OpenCV 预处理：去噪、增强、倾斜矫正、尺寸规范化
- 统一切片策略：figure/question 双图优先

**Agent 可调用工具（Function Tools）**
1) `diagram_slice(image)`  
   - 生成 figure/question 切片
2) `qindex_fetch(session_id)`  
   - 读取题目级切片（若已存在）
3) `math_verify(expression)`  
   - 必要时验证复杂计算
4) `ocr_fallback(image)`  
   - 当视觉理解失败时补充 OCR

**触发策略（由 Planner 决定）**
- 普通题：不调用 math_verify
- 复杂计算 / 多步推导 / 不确定：触发 math_verify
- 多题页图：优先切片或 qindex

---

### 4. Memory / State 设计

Session Memory 持久化：
- 原始图 URL
- 切片 URL（figure/question）
- 识别原文 ocr_text
- judgment_basis
- 结果结构化 JSON

用于：
- Chat 追问复盘
- 证据一致性校验

---

### 5. 输出结构（统一 JSON）

顶层字段（严格）：
- `ocr_text`: string  
- `results`: array  
  - `question_number`, `verdict`, `question_content`, `student_answer`
  - `reason`, `judgment_basis`, `warnings`, `knowledge_tags`
- `summary`: string  
- `warnings`: array  

**judgment_basis（中文）**
采用“观察 → 规则 → 结论”的推理链：
1) 观察（视觉/文本）
2) 规则/定义
3) 结论
必须包含“依据来源：...”一句

---

### 6. 流式输出（Streaming Tools）

支持分模块输出：
1) 批改完成提示
2) 批改结果（总览）
3) 错题展开 + 依据
4) 正确题折叠依据
5) 识别原文（折叠）

---

### 7. 可观测性（Logging/Tracing）

关键事件：
- `agent_plan_start / agent_plan_done`
- `agent_tool_call / agent_tool_result`
- `agent_reflect_pass / agent_reflect_retry`
- `agent_finalize_done`

字段建议：
`session_id`, `plan`, `tools_used`, `iterations`, `confidence`

---

### 8. 与当前实现的差异

当前：固定 pipeline + 单次 LLM 调用  
目标：Planner → Tool → Reflect → Output 循环  

改动重点在“流程控制层”，工具与模型能力可复用。

---

### 9. 迁移方案（一步到位）

1) 新增 AutonomousAgent 调度层  
2) 封装现有工具为 Function Tools  
3) 替换 grade pipeline 为 Agent orchestrator  
4) 保持 API 输出结构不变  

---

### 10. 成功指标（验收）

- 视觉题稳定性显著提升（错判率下降）
- judgment_basis 与题目内容一致
- Chat 追问不再出现“看不到图”
- 日志可直接回放 Agent 轨迹
