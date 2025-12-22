# Agent Tool Calling 能力评估分析 (Tool Calling Potential Analysis)

> **核心结论**：对于当前“作业批改”场景，**JSON Output (现行方案)** 在延迟和稳定性上优于 Tool Calling；但对于未来的“深度辅导”和“理科解题”场景，**Tool Calling** 是实现高准确率和智能化的必经之路。

---

## 1. 为什么目前我们主要用 JSON Mode (Context Injection)？

目前的架构是 **Pipeline (流水线)** 模式：
`SOP (代码逻辑) -> 准备数据 -> 塞给 LLM -> LLM 按格式吐出结果`

- **优势**：
    - **速度快**：无需 LLM 思考“我该用什么工具”，直接执行任务。
    - **可控性强**：数据流完全由代码控制，不会出现 Agent“乱调用工具”导致死循环。
    - **适合高并发**：批改作业就像“阅卷机”，追求的是吞吐量。

## 2. 引入 Tool Calling 的必要性与潜力 (Necessity & Potential)

虽然目前够用，但 Tool Calling 能解锁以下核心能力，这在当前纯 LLM 模式下是**无法解决**或**效果不佳**的：

### 场景 A：数学运算的去幻觉 (Math Verification) - **高潜力**
- **痛点**：当前 LLM（即使是 Qwen/Doubao）在做多位数加减乘除或解方程时，经常出现“一本正经胡说八道”的计算错误。
- **Tool Solution**：给 Agent 配备一个 `Calculator` 或 `Python REPL` 工具。
- **流程**：
    1. Agent 识别到算式 `123 * 456`。
    2. 暂停生成，调用 `calculate(123 * 456)`。
    3. 获取结果 `56088`，再继续生成文本。
- **价值**：**彻底根除计算类幻觉**，让数学批改的算力部分达到 100% 准确。

### 场景 B：动态查重与检索 (Dynamic RAG) - **中潜力**
- **痛点**：目前我们是“预判”需要错题库，在 Prompt 里一次性塞入。如果题目很难，Agent 发现需要查更老的知识点，它现在只能“硬猜”或“放弃”。
- **Tool Solution**：配备 `search_question_bank(query)` 工具。
- **流程**：Agent 发现题目涉及“勾股定理”，自己决定调用工具去库里搜类似的例题作为参考。
- **价值**：大幅提升处理 **“超纲题”** 或 **“综合题”** 的能力。

### 场景 C：复杂交互式辅导 (Interactive Tutoring) - **极高潜力**
- **痛点**：苏格拉底辅导目前只能“纯聊”。无法画图，无法演示。
- **Tool Solution**：
    - `draw_function_plot(formula)`: 为学生画出函数图像帮助理解。
    - `generate_similar_practice()`: 现场生成一道变式题给学生做。
- **价值**：从“聊天机器人”进化为真正的 **“AI 助教”**。

---

## 3. 引入的代价 (Trade-offs)

| 维度 | JSON Mode (现状) | Tool Calling (未来) |
| :--- | :--- | :--- |
| **延迟 (Latency)** | **低** (1次 LLM 调用) | **高** (至少 2次 LLM 调用 + 工具执行时间) |
| **稳定性** | **高** (结构化输出) | **中** (依赖模型指令遵循能力，可能调错参数) |
| **成本** | **低** | **略高** (多轮对话消耗更多 Token) |
| **模型要求** | 任意指令微调模型 | 需要支持 Function Calling 的模型 (Qwen/Doubao 均支持，但能力有差异) |

---

## 4. 发展建议 (Strategic Recommendation)

**不要为了通过 Tool Calling 而 Tool Calling，要为解决特定问题而引入。**

建议采取 **“双轨制” (Dual Track)** 策略：

1.  **保持现状 (Grading Track)**：
    - 作业批改（高频、即时）继续使用当前的 **FastAPI + JSON Mode**。追求极致速度和低成本。目前不需要动。

2.  **试点引入 (Tutoring Track)**：
    - 在未来的 **Phase 3 (辅导增强)** 中，为“苏格拉底辅导 Agent”引入工具能力。
    - **首个工具**：`VerifyCalculation` (计算器) —— 用于在辅导过程中验证学生的计算步骤。
    - **架构准备**：这时候，您之前提到的 **“工具注册 (Tool Registration)”** 就变得非常有价值了。

**总结**：
如果您的愿景是让 Agent 变得更“聪明”、更能处理复杂问题（而不仅仅是文字处理），那么 **Tool Calling 是必经之路**。它会让 Agent 从“文科生”变成“理科生”。
