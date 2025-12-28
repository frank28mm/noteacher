# Agent 架构分析报告

> 本文档基于 Google《Introduction to Agents》白皮书规范，对"作业检查大师"项目的 Agent 架构进行全面对比分析。

**分析日期**: 2025-12-27
**参考文档**: Introduction to Agents.md (Google Agent Whitepaper Series)
**分析范围**: `homework_agent/services/` 核心 Agent 实现

---

## 1. 总体评估

| 维度 | 评分 | 说明 |
|------|------|------|
| **架构设计** | 8/10 | 更接近 Level 2（单 Agent 内部多角色流水线），非 Level 3 跨 Agent 协作 |
| **工具设计** | 7/10 | 工具职责清晰、返回结构化；但未做到“所有最佳实践”（入/出参 schema、输出净化等仍可加强） |
| **上下文工程** | 7/10 | SessionState/plan_history 组织良好；但缺“跨会话/用户级长期记忆”体系 |
| **可观测性** | 6/10 | 有结构化日志与轻量 trace_start/trace_end；缺 Metrics 聚合与分布式 tracing（OpenTelemetry） |
| **评估体系** | 4/10 | 有反思/置信度门槛；缺 Golden Dataset、离线回归评估与 CI 门禁 |
| **安全防护** | 5/10 | `math_verify` 有一定沙箱/白名单；但缺系统级 prompt-injection 防护、PII 输出过滤、HITL 流程 |

**综合评分（粗略）**: **6.2/10** - 具备“可运行原型/试运行”基础，但距离“生产就绪”仍有关键差距（评估、治理、监控、安全）

---

## 2. 核心架构对比

### 2.1 四大核心组件 - 完全符合

| 组件 | 文档要求 | 项目实现 | 代码位置 | 状态 |
|------|---------|---------|----------|------|
| **模型 (The Brain)** | 推理引擎 | `LLMClient` + 多 provider 支持 | `services/llm.py` | ✅ |
| **工具 (The Hands)** | 连接外部世界 | `diagram_slice`, `math_verify`, `ocr_fallback`, `qindex_fetch`, `vision_roi_detect` | `services/autonomous_tools.py` | ✅ |
| **编排层 (Nervous System)** | 管理循环 | `PlannerAgent` → `ExecutorAgent` → `ReflectorAgent` → `AggregatorAgent` | `services/autonomous_agent.py` | ✅ |
| **部署 (Body & Legs)** | 服务化 | 有 FastAPI 路由与 SessionState 存储；但“生产级部署/治理/运行时服务”需要结合实际部署方式与运维体系评估 | `api/` + `services/session_state.py` | ⚠️ |

### 2.2 五步问题解决循环 - 完美实现

文档定义的循环：
```
Get Mission → Scan Scene → Think → Act → Observe
```

项目实现映射：

| 步骤 | 文档描述 | 项目实现 | 代码位置 |
|------|---------|---------|----------|
| **Get Mission** | 获取任务 | `run_autonomous_grade_agent()` 接收 `images` + `subject` | [autonomous_agent.py:484](homework_agent/services/autonomous_agent.py#L484) |
| **Scan Scene** | 感知环境 | `PreprocessingPipeline` + `SessionState` 聚合上下文 | [autonomous_agent.py:514](homework_agent/services/autonomous_agent.py#L514) |
| **Think** | 规划 | `PlannerAgent.run()` 输出结构化执行计划 | [autonomous_agent.py:154](homework_agent/services/autonomous_agent.py#L154) |
| **Act** | 行动 | `ExecutorAgent.run()` 调用工具 | [autonomous_agent.py:223](homework_agent/services/autonomous_agent.py#L223) |
| **Observe & Iterate** | 观察迭代 | `ReflectorAgent.run()` 评估 + 循环直到 `confidence >= 0.90` | [autonomous_agent.py:353](homework_agent/services/autonomous_agent.py#L353) |

**流程图**:
```
用户请求 → PreprocessingPipeline (场景感知)
         ↓
    PlannerAgent (思考: 制定计划)
         ↓
    ExecutorAgent (行动: 执行工具)
         ↓
    ReflectorAgent (观察: 评估信心)
         ↓
    confidence >= 0.90?
         ├─ Yes → AggregatorAgent (输出)
         └─ No  → 循环回 PlannerAgent (最多3次)
```

---

## 3. 高级特性符合度分析

### 3.1 多 Agent 系统 (Level 3) - **不完全符合（更接近 Level 2）**

白皮书中的 Level 3 强调“多个自治 Agent 的协作”，典型特征是：**Agent 把其他 Agent 当作工具/服务去调用**（跨进程/跨团队/跨框架也可），并涉及 agent discovery、通信协议（如 A2A）与分布式 tracing。

本项目当前实现更像是 **单一 Agent 的内部“多角色流水线”**（模块化拆分）：Planner/Executor/Reflector/Aggregator 的职责划分非常清晰，但它们仍在同一运行时内协同，并未体现“跨 Agent 服务化协作”。

项目实现（内部模块职责分工）：

```python
# 明确的职责分工
PlannerAgent    → "分析题目结构，决定工具调用顺序"
ExecutorAgent   → "执行工具调用 (diagram_slice, math_verify, ocr_fallback)"
ReflectorAgent  → "验证证据一致性，决定是否重新规划"
AggregatorAgent → "综合证据，输出最终批改结果"
```

**对比文档**:
> "Coordinator pattern: introduces a 'manager' agent that analyzes a complex request, segments the primary task, and intelligently routes each sub-task to the appropriate specialist agent."

**符合点（作为“内部 coordinator”）**:
- ✅ 明确的角色分离
- ✅ 结构化通信 (JSON payload)
- ✅ 循环协作 (Plan → Execute → Reflect → Repeat)

**仍缺失的 Level 3 关键要素（事实层面）**:
- ❌ 未见 A2A/Remote Agent（AgentCard、跨服务调用等）
- ❌ 未见跨 Agent 的分布式 tracing（trace_id 贯穿多个 agent/service）

### 3.2 上下文工程 - 符合

文档强调 **"Context Engineering over Prompt Engineering"**。

项目实现：

| 组件 | 文档要求 | 项目实现 |
|------|---------|---------|
| **短时记忆** | Scratchpad | `SessionState.image_urls`, `ocr_text`, `plan_history` |
| **状态管理** | Structured State | `SessionState` dataclass with `to_dict()` / `from_dict()` |
| **会话级持久化** | Session persistence | `CacheSessionStore` with TTL（按 `session_id` 保存/恢复会话状态） |
| **动态组装** | Runtime Context Assembly | `build_planner_user_prompt(state_payload=payload)` |

说明：`CacheSessionStore` 更接近白皮书里“Session Store/短期状态持久化”，并不等价于“跨会话/用户级长期记忆（Memory Manager）”。目前代码中未看到按 `user_id` 聚合的长期记忆、记忆检索/更新、记忆净化与 provenance 等机制。

**SessionState 结构** ([session_state.py:16](homework_agent/services/session_state.py#L16)):
```python
@dataclass
class SessionState:
    session_id: str
    image_urls: List[str]
    slice_urls: Dict[str, List[str]]  # figure, question slices
    ocr_text: Optional[str]
    plan_history: List[Dict[str, Any]]  # Planning trajectory
    tool_results: Dict[str, Any]         # Tool execution results
    reflection_count: int                # Loop iterations
    slice_failed_cache: Dict[str, bool]  # Failure memory
    attempted_tools: Dict[str, Dict]     # Tool status tracking
    preprocess_meta: Dict[str, Any]      # Preprocessing metadata
    warnings: List[str]                  # Accumulated warnings
```

**符合点**:
- ✅ 结构化状态管理
- ✅ 持久化存储 (TTL)
- ✅ 上下文压缩 (`plan_history[-2:]` 只保留最近2次)

### 3.3 工具设计最佳实践 - 符合

文档要求 ([Agent Tools & MCP.md](Agent Tools & Interoperability with MCP.md)):

| 最佳实践 | 文档要求 | 项目实现 |
|---------|---------|---------|
| **清晰命名** | `create_critical_bug_in_jira` | `diagram_slice`, `vision_roi_detect`, `math_verify` ✅ |
| **描述动作** | "create bug" not "use create_bug" | Prompt 中明确告知工具用途 ✅ |
| **粒度化** | 每个工具单一职责 | 每个工具专注单一功能 ✅ |
| **简洁输出** | 不返回大数据 | 返回 `{"status": "ok", "urls": {...}}` ✅ |
| **错误消息** | 给出指导性错误 | `{"reason": "roi_not_found"}` ✅ |
| **验证有效使用** | Schema validation | Pydantic models for all payloads ✅ |

**工具示例** ([autonomous_tools.py:129](homework_agent/services/autonomous_tools.py#L129)):
```python
def diagram_slice(*, image: str, prefix: str) -> Dict[str, Any]:
    """
    Run OpenCV pipeline to slice diagram and question regions.

    Returns:
        {"status": "ok", "urls": {...}, "warnings": [...], "reason": "..."}
        {"status": "error", "message": "...", "reason": "roi_not_found"}
    """
```

**符合点**:
- ✅ 函数签名清晰
- ✅ 返回结构化结果
- ✅ 包含 `reason` 字段指导下一步操作

---

## 4. 部分符合/需要关注的点

### 4.1 可观测性 - 部分符合

文档要求三大支柱：**Logs, Traces, Metrics**

| 支柱 | 文档要求 | 项目实现 | 状态 |
|------|---------|---------|------|
| **Logs** | 详细日志记录 | `log_event(..., "agent_plan_start")` | ✅ |
| **Traces** | 端到端追踪 | `trace_span` 以 `trace_start/trace_end` JSON 日志形式记录 span（非 OpenTelemetry 分布式 tracing） | ⚠️ |
| **Metrics** | 聚合指标面板 | 仅在日志字段中记录 `duration_ms/iteration`，未见指标聚合导出与仪表板 | ❌ |

**当前日志示例** ([autonomous_agent.py:559-586](homework_agent/services/autonomous_agent.py#L559)):
```python
log_event(planner_logger, "agent_plan_start",
          session_id=session_id, iteration=iteration+1)
log_event(planner_logger, "agent_plan_done",
          duration_ms=int((time.monotonic() - plan_started) * 1000))
```

**缺失**:
- ❌ 指标聚合与导出（例如 task_success_rate、avg_iterations_per_task、tool_error_rate、latency_p95/p99）
- ❌ 可视化仪表板（Grafana / Cloud Monitoring 等）
- ❌ 告警规则（latency/error_rate/cost 的阈值告警）
- ⚠️ 分布式 tracing：当前是“轻量 trace 日志”，缺 trace_id 跨服务贯通与 trace UI

### 4.2 评估体系 - 部分符合

文档强调 ([Prototype to Production.md](Prototype to Production.md)):
- 自动化评估
- Golden Dataset
- LLM-as-a-Judge

| 组件 | 文档要求 | 项目实现 | 状态 |
|------|---------|---------|------|
| **自我评估** | Agent 自我判断 | `ReflectorAgent` (`pass` + `confidence`) | ✅ |
| **Golden Dataset** | 预定义测试集 | ❌ 缺失 | ❌ |
| **离线评估** | CI/CD 集成 | ❌ 缺失 | ❌ |
| **A/B Testing** | 版本对比 | ❌ 缺失 | ❌ |

**ReflectorAgent 评估逻辑** ([autonomous_agent.py:346-388](homework_agent/services/autonomous_agent.py#L346)):
```python
class ReflectorAgent:
    async def run(self, state: SessionState, plan: List[Dict]) -> ReflectorPayload:
        # 评估证据质量
        # 返回: pass (bool), confidence (0.0-1.0), issues, suggestion
```

**建议改进**:
1. 创建代表性测试集 (数学/英语作业各50+样本)
2. CI/CD 中集成评估门禁
3. 自动回归测试 (PR 前必须通过)

### 4.3 安全防护 - 基础符合

文档强调多层防御 ([Introduction to Agents.md](Introduction to Agents.md)):
- 确定性护栏
- AI 驱动的护栏
- Human-in-the-Loop (HITL)

| 层级 | 文档要求 | 项目实现 | 状态 |
|------|---------|---------|------|
| **输入验证** | 白名单机制 | `ALLOWED_SYMPY_FUNCS` | ✅ |
| **局部沙箱** | 隔离/最小权限 | 目前主要体现在 `math_verify`（AST 检查 + 白名单 + timeout）；不等同于系统级沙箱 | ⚠️ |
| **输出过滤** | 安全过滤 | 未见通用 PII/敏感信息输出过滤与脱敏策略 | ❌ |
| **HITL** | 人工确认 | 未见审核队列/人工确认流程（仅置信度门槛） | ❌ |

**沙箱实现** ([autonomous_tools.py:308-339](homework_agent/services/autonomous_tools.py#L308)):
```python
ALLOWED_SYMPY_FUNCS = {"simplify", "expand", "solve", "factor", "sympify"}

def math_verify(*, expression: str) -> Dict[str, Any]:
    # AST 检查禁止 token
    if any(x in cleaned for x in ("__", "import", "exec", "eval", "open")):
        return {"status": "error", "message": "forbidden_token"}

    # 只允许白名单函数
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = getattr(node.func, "id", "")
            if func_name not in ALLOWED_SYMPY_FUNCS:
                return {"status": "error", "message": "forbidden_function"}
```

**缺失**:
- ❌ PII (个人隐私信息) 过滤
- ❌ Prompt Injection 防护
- ❌ HITL 人工审核环节 (低 confidence/uncertain 情况)

---

## 5. 超出文档的亮点设计

### 5.1 智能故障恢复策略

文档未详细阐述，但项目中实现完善。

**Planner 强制降级** ([autonomous_agent.py:186-214](homework_agent/services/autonomous_agent.py#L186)):
```python
# Planner failure strategy: 强制降级路径
if diagram_issue or slice_failed:
    forced_plan = [
        {"step": "qindex_fetch", "args": {"session_id": state.session_id}},
        {"step": "vision_roi_detect", "args": {"image": image}},
        {"step": "ocr_fallback", "args": {"image": image}},
    ]
```

**优势**:
- 避免无限循环
- 优雅降级 (VLM → OCR → 纯文本)
- 提高成功率

### 5.2 多层缓存优化

文档提到缓存重要性，项目实现更细致。

**三层缓存** ([autonomous_tools.py:34-40](homework_agent/services/autonomous_tools.py#L34)):
```python
OCR_CACHE_PREFIX = "ocr_cache:"           # OCR 结果缓存 (24h)
SLICE_FAILED_CACHE_PREFIX = "slice_failed:" # 切片失败缓存 (1h)
QINDEX_CACHE_PREFIX = "qindex_slices:"     # 问题索引缓存 (1h)
```

**优势**:
- 降低 API 成本
- 减少响应延迟
- 避免重复失败

### 5.3 PreprocessingPipeline 三层降级

项目独有的创新设计。

```python
# A (qindex cache) → B (VLM locator) → C (OpenCV fallback)
pipeline = PreprocessingPipeline(session_id=session_id)
for ref in images:
    result = await pipeline.process_image(ref, use_cache=True)
```

**降级路径**:
1. **Layer A**: qindex 缓存命中 (最快)
2. **Layer B**: VLM 定位器 (SiliconFlow)
3. **Layer C**: OpenCV 传统 CV 算法

**优势**:
- 成本最优 (缓存优先)
- 准确性保障 (VLM fallback)
- 兜底方案 (OpenCV)

---

## 6. 改进建议 (优先级排序)

### 6.1 [高优先级] 添加 Golden Dataset 评估

**参考**: `Prototype to Production.md` Section 3.1

**实施步骤**:
1. 创建代表性测试集
   - 数学作业: 50+ 样本 (几何、代数、计算)
   - 英语作业: 30+ 样本 (阅读理解、完形填空)
2. 定义评估指标
   - `task_success_rate`: 任务完成率
   - `verdict_accuracy`: verdict 准确率
   - `avg_iterations`: 平均迭代次数
3. CI/CD 集成
   - PR 前自动运行评估
   - 阻止退化 (性能下降 > 5%)

**预期收益**:
- 防止回归
- 量化改进效果
- 加快迭代速度

### 6.2 [中优先级] 增强可观测性

**参考**: `Agent Quality.md` Chapter 3 - Observability

**实施步骤**:
1. 添加 Metrics 导出
   ```python
   from prometheus_client import Counter, Histogram

   task_success = Counter('agent_task_success', 'Task success rate', ['subject'])
   task_duration = Histogram('agent_task_duration_seconds', 'Task duration')
   iteration_count = Histogram('agent_iteration_count', 'Iterations per task')
   ```
2. 可视化仪表板
   - Grafana / CloudWatch Dashboard
   - 实时指标面板
3. 告警规则
   - `error_rate > 10%` 触发告警
   - `latency_p99 > 30s` 触发告警

**预期收益**:
- 实时监控生产健康度
- 快速定位问题
- 数据驱动优化

### 6.3 [中优先级] 添加 HITL (Human-in-the-Loop)

**参考**: `Introduction to Agents.md` Section 7 - Securing a Single Agent

**实施步骤**:
1. 定义触发条件
   - `confidence < 0.80`
   - `verdict == "uncertain"`
   - `diagram_roi_not_found`
2. 创建审核队列
   - Redis/Database 存储待审核任务
   - Web UI 展示待审核项
3. 人工反馈集成
   - 人工修正结果
   - 反馈写入 Golden Dataset

**预期收益**:
- 提高边界情况准确率
- 持续改进模型
- 用户信任度提升

### 6.4 [中优先级] 补齐“长期记忆（Memory）”而不仅是 Session TTL

**参考**: `Context Engineering_ Sessions & Memory.md`

**澄清现状**:
- 当前 `CacheSessionStore` 是会话级持久化（按 `session_id`），主要解决“短期状态恢复”。
- 若要符合白皮书对 Memory 的定义，需要跨会话、按 `user_id` 的记忆抽取/整合/检索（并解决隐私、投毒、provenance）。

**实施方向**:
1. 设计 memory scope（至少 user-level；可选 app-level procedural memory）
2. Memory generation（提取/合并）后台化（避免阻塞主流程）
3. Retrieval 策略：proactive 或 memory-as-a-tool，并增加脱敏/净化

### 6.5 [低优先级] A2A 协议支持（当确实需要“跨 Agent/跨团队”协作时）

**参考**: `Prototype to Production.md` Section 6 - A2A

**适用场景**:
- 需要多个 Agent 协作
- 跨系统调用

**实施步骤**:
1. 暴露 Agent 为 A2A 服务
   ```python
   from google.adk.a2a.utils.agent_to_a2a import to_a2a
   a2a_app = to_a2a(root_agent, port=8001)
   ```
2. 发布 Agent Card
3. 其他 Agent 通过 `RemoteA2aAgent` 调用

**预期收益**:
- Agent 间互操作性
- 模块化复用

---

## 7. 总结

### 7.1 核心优势

1. **架构清晰**: 单 Agent 内部多角色（Planner/Executor/Reflector/Aggregator）分工明确，贴合 Level 2 的“策略型问题求解”
2. **工具设计较好**: 工具职责清晰、返回结构化、具备降级路径，但仍可补齐 schema/输出净化等“生产级细节”
3. **鲁棒性强**: 多层缓存 + 故障恢复 + 降级策略
4. **代码质量高**: 清晰的职责分离 + 类型安全 (Pydantic)

### 7.2 改进空间

1. **评估体系**: 缺少 Golden Dataset 和自动化回归测试
2. **可观测性**: 有日志/追踪，缺指标聚合和可视化
3. **安全防护**: 有沙箱，缺 HITL 和输出过滤

### 7.3 生产就绪度

| 维度 | 状态 | 说明 |
|------|------|------|
| **功能完整性** | ✅ 就绪 | 核心流程完善 |
| **性能优化** | ✅ 就绪 | 多层缓存/降级优化 |
| **质量保障** | ❌ 待完善 | 需 Golden Dataset + 离线回归评估 + CI 门禁 |
| **运维监控** | ❌ 待完善 | 需 Metrics 聚合/面板/告警；tracing 建议升级为 OTel |
| **安全合规** | ❌ 待完善 | 需 prompt-injection/PII 输出过滤/HITL/权限边界等系统级防护 |

**建议**:
- **短期**: Golden Dataset + CI/CD 评估门禁；补齐基础输出过滤（PII/敏感信息）
- **中期**: 指标体系（Metrics/告警）与 tracing 升级（OpenTelemetry）；引入 HITL 审核队列
- **长期**: 记忆系统（Memory Manager）与（确有需求时）A2A 互操作性

---

## 8. 参考资料

- [Introduction to Agents.md](docs/agent/Introduction%20to%20Agents.md)
- [Agent Tools & MCP.md](docs/agent/Agent%20Tools%20%26%20Interoperability%20with%20MCP.md)
- [Agent Quality.md](docs/agent/Agent%20Quality.md)
- [Context Engineering: Sessions, Memory.md](docs/agent/Context%20Engineering_%20Sessions%20%26%20Memory.md)
- [Prototype to Production.md](docs/agent/Prototype%20to%20Production.md)

---

**文档版本**: v1.0
**最后更新**: 2025-12-27
**维护者**: Claude Code Agent
