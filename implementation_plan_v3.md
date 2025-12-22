# Implementation Plan v3 (Expanded): Tool-Enabled Agent Architecture & Vision Enhancement

> **定位**：参考 Google ADK 文档中的“Function Tools / Tool Performance / Action Confirmation / Context Compaction / Evaluation Criteria / Streaming”等理念，**不迁移 ADK**，在现有 FastAPI 架构内逐步对齐。  
> **输入**：`task.md` + `docs/google_adk_evaluation_report.md` + `docs/tool_calling_potential_analysis.md`

## Goals
- 把当前“text-in → text-out”的 Agent 升级为**可工具调用**的工作流。
- 对“视觉→批改→辅导”的链路做结构化增强与可观测性提升。
- 保持“批改高吞吐 + 辅导高准确”的双轨策略。

## Non-Goals
- 不迁移 ADK / Genkit / Vertex AI。
- 不更换模型供应商（继续支持 SiliconFlow + Ark/Doubao）。

## ADK 借鉴点（落地成我们的工程约束）
- **Function Tools**：统一工具注册与 JSON Schema（装饰器/注册表）。  
- **Long-Running Tools**：工具可产出进度（流式/事件），适配 SSE。  
- **Tool Performance**：并行工具调用、异步 I/O、线程池处理 CPU 任务、分块与让出执行权。  
- **Action Confirmation**：对高风险工具调用允许“确认/继续”。  
- **Context Compaction**：滑动窗口 + 事件摘要，降低上下文体积。  
- **Evaluation Criteria**：幻觉率、工具使用质量、响应安全性。  

---

## Phase 1: 工具基础设施 (Tool Infrastructure)

### 1.1 Tool Registry + `@tool` 装饰器
目标：对齐 ADK Function Tools 风格，统一 Schema、注册、执行入口。
- `ToolRegistry`：注册、查询、生成 OpenAI-compatible schema。  
- `@tool`：从函数签名/类型注解/Docstring 生成参数 schema。  
- 约束：schema 必须稳定（CI snapshot），避免 prompt 漂移。  

### 1.2 Tool Runtime (ReAct Loop)
目标：在 `llm.py` 的 tutor 流中引入可控的工具调用回路。
- 最大步数限制（防无限循环）。  
- 处理 `tool_calls → tool_result → assistant` 的完整链路。  
- 失败策略：工具异常 → 返回可解释错误 + 回退文本。  

### 1.3 Long-Running Tools (流式/事件)
目标：支持“工具产出进度 + SSE 更新”。  
借鉴 ADK `LongRunningFunctionTool` 思路：
- 工具函数允许 `yield` 进度事件（progress）。  
- SSE 层把 progress 作为“中间事件”写回前端。  
- 结束时输出 final response。  

### 1.4 Agent-as-Tool（可选但推荐）
目标：让子 Agent 作为工具被主 Agent 调用，避免“完全移交”。
- **Agent-as-Tool**：主 Agent 保持控制权，子 Agent 只提供结果。  
- **Sub-agent**：完全移交给子 Agent（仅在明确需要时启用）。  

### 1.5 Action Confirmation（安全/成本型工具）
目标：高风险工具调用支持确认（human-in-the-loop）。
- 为工具增加 `require_confirmation` 元数据。  
- 允许“自动确认规则”（例如金额阈值）。  
- 支持 REST/SSE “确认后续执行”。  

### 1.6 Tool Performance 指南落地
ADK 关键建议对应到我们的实现约束：
- **异步 I/O**：所有外部 API Tool 使用 `async`。  
- **CPU 密集**：用线程池（`run_in_executor`）。  
- **长列表处理**：分块 + `await asyncio.sleep(0)` 让出执行权。  
- **并行提示**：在 Prompt/Tool 描述中明确“可并行调用”。  

### 1.7 验证
自动化：
- Tool schema snapshot  
- Tool call loop (max steps / error handling)  
手动：
- Tutor 调用 `verify_calculation` 并回写结果  

---

## Phase 2: 视觉增强 (Vision Enhancement)

### 2.1 Image Preprocessor
目标：低质图片稳定识别。
- `denoise / enhance_contrast / deskew` 三步流水线  
- 集成到 OCR / qindex / vision upstream  

### 2.2 Vision Tools
目标：让 Agent 可主动纠正 OCR 上下文。
- `correct_ocr_context(text, context)`  
- 约束：必须提供“纠错依据”  

### 2.3 Vision 性能与可靠性
参考 ADK 工具性能：
- 串行变并行：多页图片/多切片并行调用  
- 分块处理：大图分块 + 让出执行权  
- 失败重试策略可控（限次数/限时）  

### 2.4 验证
- 低质量图片识别率对比  
- OCR 纠错工具调用验证  

---

## Phase 3: Prompt 管理 (Prompt Management)

### 3.1 PromptManager
目标：Prompts 版本化 + 热加载。
- YAML + Jinja2  
- 版本号 + 环境配置切换  

### 3.2 Prompt 结构化输出
- 强制结构化：Grade/Chat 共用 schema  
- Prompt 变化必须走快照测试  

---

## Phase 4: 可观测性与评测 (Observability + Evaluation)

### 4.1 观测埋点
对齐 ADK Logging/Trace：
- `tool_call_start / tool_call_done / tool_call_error`  
- `llm_start / llm_done / llm_error`  
- 记录 `tool_name / latency_ms / args_hash`  

### 4.2 评测指标（ADK Criteria 借鉴）
- **hallucinations**：响应是否被上下文支持  
- **tool_use_quality**：工具调用路径是否正确  
- **safety**：输出安全性  
落地方式：  
1) 基准样本集（20-50条）  
2) LLM-as-judge + 阈值  
3) 失败例自动归档  

---

## Phase 5: Context & Memory（性能保障）

### 5.1 Context Compaction
借鉴 ADK “滑动窗口 + summarizer”：
- compaction_interval / overlap_size  
- summarizer 采用轻量模型  
- 归档为 `session_summary`  

### 5.2 Session / Memory
- 统一 session_id / user_id  
- 引入“短期对话上下文 + 长期摘要”双层结构  

---

## Verification Plan (Expanded)
- Tool Infra：schema稳定、tool call loop 测试  
- Vision：低质图识别率提升  
- Prompt：回归一致性快照  
- Observability：trace + tool log 完整性  
- Evaluation：幻觉率/工具调用质量基线  

---

## Workload Estimate (Updated)
| Phase | 预估工时 |
| :--- | :--- |
| Phase 1: Tool Infra | 2.0 Days |
| Phase 2: Vision | 1.5 Days |
| Phase 3: Prompts | 0.5 Day |
| Phase 4: Observability + Eval | 1.0 Day |
| Phase 5: Context & Memory | 0.5 Day |
| **Total** | **~5.5 Days** |

---

## Risks & Mitigations
- **工具调用失控**：最大步数 + 失败降级  
- **性能抖动**：并行 + 缓存 + 线程池  
- **Prompt 漂移**：快照测试 + 版本锁  
- **评测成本上升**：小规模样本先跑  
