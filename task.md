# Task: Tool-Enabled Agent Architecture & Vision Enhancement (Expanded)

> 参考 `implementation_plan_v3.md`

## Checklist

### Phase 1: 工具基础设施 (Tool Infrastructure)
- [ ] 创建 `homework_agent/core/tools.py` (ToolRegistry & `@tool` 装饰器)
- [ ] 新增 `homework_agent/tools/math_tools.py` (`verify_calculation`)
- [ ] 更新 `homework_agent/services/llm.py` 支持 Tool Calling (ReAct Loop)
- [ ] 支持 Long-Running Tool 进度事件（用于 SSE）
- [ ] 评估/设计 Agent-as-Tool（主 Agent 保持控制权）
- [ ] 评估/设计 Action Confirmation（高风险工具确认）
- [ ] 性能规则：并行调用提示、异步 I/O、CPU 任务线程池、长列表分块 + `await asyncio.sleep(0)`
- [ ] 验证：辅导能调用计算器并回写结果

### Phase 2: 视觉增强 (Vision Enhancement)
- [ ] 创建 `homework_agent/services/image_preprocessor.py` (denoise/enhance/deskew)
- [ ] 集成 Preprocessor 到 OCR / qindex / vision upstream
- [ ] 创建 `homework_agent/tools/vision_tools.py` (`correct_ocr_context`)
- [ ] 并行化多页/多切片处理策略（含重试上限）
- [ ] 验证：低质量图片识别率提升（前后对比）

### Phase 3: Prompt 管理 (Prompt Management)
- [ ] 创建 `homework_agent/utils/prompt_manager.py`
- [ ] 迁移 prompts 至 `homework_agent/prompts/*.yaml`
- [ ] Prompt 版本化 + 快照测试

### Phase 4: 可观测性与评测 (Observability + Evaluation)
- [ ] 统一 log_event：`tool_call_start/done/error`, `llm_start/done/error`
- [ ] 评测基线：幻觉率 / 工具使用质量 / 安全性
- [ ] 小规模样本集 (20-50) + LLM-as-judge 评测跑通

### Phase 5: Context & Memory
- [ ] 上下文压缩（滑动窗口 + summarizer）
- [ ] Session / Memory 双层结构（短期对话 + 长期摘要）

