# Autonomous Grade Agent 工程落地计划（详细版）

> 目标：按 `docs/autonomous_grade_agent_design.md` 一步到位落地“自主阅卷 Agent”。
> 范围：数学 / 英语。

---

## 0. 范围与原则

- **不做** OCR 快速通道、Router/fast path。
- **OpenCV 前置流水线固定执行**（去噪/矫正/切片策略），不由 Agent 决策。
- **Agent 自主性**：Planner → Executor → Reflector → Aggregator，支持 Loop。
- **输出必须结构化**：`vision_raw_text + results + judgment_basis + summary + warnings`。
- **Chat 只读 /grade 结果**，不实时看图。

---

## 1. ToDo 列表（按优先级）

### P0（必须）
1. **SessionState 类骨架**
   - 位置：`homework_agent/services/session_state.py`
   - 字段：详见 §2.1
2. **AutonomousAgent 类骨架**
   - 位置：`homework_agent/services/autonomous_agent.py`
   - 方法：`plan() / execute() / reflect() / aggregate()`
   - Loop 控制：`max_iterations=3`，终止条件写死
3. **Orchestration 文档化**
   - 顺序编排 + Loop 退出机制（详见 §2.4）

### P1（强烈建议）
4. **实现 4 个子 Agent**
   - Planner / Executor / Reflector / Aggregator
5. **封装 Function Tools（仅 4 个）**
   - diagram_slice / qindex_fetch / math_verify / ocr_fallback
6. **SessionState 持久化接口**（内存/Redis 双模式）
7. **Aggregator 兼容映射**（results → wrong_items）
8. **Planner 输入注入 reflection_result**（issues/suggestion 作为下一轮规划依据）
9. **Executor 重试机制**（1-2 次 + 简单退避）
10. **Aggregator 图片限量**（figure+question 各 1 张，最多 2 张）
11. **降级链条写死**（diagram_slice 失败 → 自动转 ocr_fallback）
12. **Rate limit 处理**（429 退避/重试策略文档化）

### P2（集成）
8. **/grade 直接替换为 AutonomousAgent**
   - 删除旧 pipeline 调用
   - 保持响应结构兼容

---

## 2. 关键工程设计

### 2.1 SessionState 结构（必须）

```python
class SessionState:
    session_id: str
    image_urls: list[str]            # Source: User upload
    slice_urls: dict[str, list[str]] # Source: diagram_slice. Keys: "figure", "question"
    ocr_text: str | None             # Source: vision/ocr_fallback
    
    # Agent Communication State
    current_plan: dict               # Source: PlannerAgent. Plan JSON.
    tool_results: dict               # Source: ExecutorAgent. {tool_name: result}
    reflection_result: dict          # Source: ReflectorAgent. {pass, confidence, issues}
    partial_results: dict            # Source: AggregatorAgent (intermediate)
    
    plan_history: list[dict]         # List of previous plans with timestamps
    reflection_count: int            # Current iteration count (0-based)
    warnings: list[str]              # System-level warnings
```

**用途**：Loop 多轮共享状态，避免把所有证据塞进 Prompt History。

### 2.2 Output Key / State 映射表（必须）

| Agent | output_key | 写入内容 | 读取方 |
| --- | --- | --- | --- |
| PlannerAgent | `current_plan` | 执行计划 JSON | Executor / Reflector |
| ExecutorAgent | `tool_results` | 工具调用结果 | Reflector / Aggregator |
| ReflectorAgent | `reflection_result` | pass/issues/confidence | Loop 控制 |
| AggregatorAgent | `final_grading_result` | 完整批改 JSON | grade 返回 |

### 2.3 SessionState 持久化接口（必须）

**默认：内存模式**（当前无用户/单机调试）。
**可选：Redis 模式**（多 worker/多进程）。

```python
class SessionStore(ABC):
    @abstractmethod
    def save(self, session_id: str, state: SessionState) -> None:
        """Persist state (Memory/Redis)"""
        ...

    @abstractmethod
    def load(self, session_id: str) -> SessionState:
        """Load state"""
        ...
```

**Output Key / State Code Access Pattern:**
```python
# Writer (Planner)
def _plan(self, state: SessionState) -> dict:
    plan = self.planner.run(state)
    state.current_plan = plan  # Write strictly to defined field
    state.plan_history.append({"iter": state.reflection_count, "plan": plan})
    return plan

# Reader (Executor)
def _execute(self, state: SessionState) -> dict:
    plan = state.current_plan  # Read strictly from defined field
    # ... execution logic ...
```

**建议 Redis 键**：`autonomous:state:{session_id}`

### 2.4 Orchestration（ADK Style，必须）

**顺序编排**：
1. PlannerAgent → 生成执行计划
2. ExecutorAgent → 执行工具
3. ReflectorAgent → 自检/纠错
4. AggregatorAgent → 输出结果

**Loop 规则（写死）**：
- `pass=true` 且 `confidence >= 0.90` → 退出 Loop
- `pass=false` → 重新触发 Planner
- `max_iterations=3` 触顶 → 强制退出并追加 warning

**规划输入（必须包含）**：
- `reflection_result`：上一轮的 issues / suggestion，避免重复 plan

**伪代码**：
```python
for i in range(MAX_ITER):
    plan = planner(state)
    tools = executor(plan, state)
    reflection = reflector(state, tools)
    if reflection.pass and reflection.confidence >= 0.90:
        break
else:
    state.warnings.append("Loop max iterations reached")

result = aggregator(state)
```

### 2.5 Function Tools 边界（必须）

- **只封装 4 个工具**：diagram_slice / qindex_fetch / math_verify / ocr_fallback
- **不封装**：vision.py 重试逻辑、llm.py JSON 修复逻辑
- **Executor 负责统一超时/重试/异常处理**
  - 默认重试 1-2 次
  - 退避：0.5s → 1.0s
- **math_verify**：必须使用安全沙箱（sympy + ast.literal_eval）

**降级链条（P1）**：
- 若 `diagram_slice` 连续失败 → 自动触发 `ocr_fallback`
- `ocr_fallback` 失败时只保留已知 evidence，并标记 warning

### 2.6 Aggregator 兼容映射（必须）

- 输出 `results` 全量题目列表（含 correct/incorrect/uncertain）
- 同步生成 `wrong_items`：
  - `verdict == incorrect` → 写入 wrong_items
  - `verdict == uncertain` → **不写入 wrong_items**，但保留在 results

**Aggregator 图片选择策略（必须）**
- 优先：`figure` 切片第 1 张 + `question` 切片第 1 张
- 最多 2 张；若切片为空才回退原图

### 2.7 SSE 事件格式（必须）

**事件命名**（严格固定）：

```
event: agent_plan_start
data: {"agent":"planner","iteration":1,"message":"正在分析题目结构..."}

event: agent_tool_call
data: {"tool":"diagram_slice","status":"running","iteration":1}

event: agent_tool_done
data: {"tool":"diagram_slice","status":"completed","iteration":1,"duration_ms":1200}

event: agent_reflect_pass
data: {"pass":true,"confidence":0.92,"iteration":1}

event: agent_reflect_fail
data: {"pass":false,"issues":["..."],"iteration":1}

event: agent_finalize_done
data: {"total_iterations":2,"duration_ms":15000}
```

**字段约束**：
- `iteration`：从 1 开始递增
- `status`：`running` | `completed` | `error`
- `duration_ms`：毫秒
- `pass`：仅在 reflect 事件中出现

### 2.8 math_verify 沙箱实现（必须）

**白名单**（仅允许）：
- `sympy.simplify`, `sympy.expand`, `sympy.solve`, `sympy.factor`, `sympy.sympify`
- 允许 `ast.literal_eval` 解析数值字面量

**黑名单**（必须拒绝）：
- `import`, `exec`, `eval`, `open`, `__import__`, `__builtins__`

**超时控制**（防卡死）：

```python
import ast
import sympy
import signal
from contextlib import contextmanager

ALLOWED_NAMES = {"simplify", "expand", "solve", "factor", "sympify"}

@contextmanager
def timeout_context(seconds: int):
    def timeout_handler(_signum, _frame):
        raise TimeoutError("Expression evaluation timeout")
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)

def math_verify(expression: str) -> dict:
    cleaned = (expression or "").replace("\n", "").strip()
    if any(x in cleaned for x in ("__", "import", "exec", "eval", "open")):
        return {"status": "error", "message": "forbidden token"}
    tree = ast.parse(cleaned, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if getattr(node.func, "id", "") not in ALLOWED_NAMES:
                return {"status": "error", "message": "forbidden function"}
    try:
        with timeout_context(5):
            result = sympy.simplify(sympy.sympify(cleaned))
        return {"status": "ok", "result": str(result)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

### 2.9 SessionState 字段值示例（必须）

```python
SessionState(
    session_id="sess_123",
    image_urls=["https://cdn.example.com/page1.jpg"],
    slice_urls={"figure": ["https://cdn.example.com/fig1.jpg"], "question": []},
    ocr_text="9. 判断∠2与∠BCD的关系...",
    plan_history=[
        {
            "iteration": 1,
            "plan": [{"step": "diagram_slice", "args": {"image": "page1"}}],
            "timestamp": "2025-01-15T10:30:00Z"
        }
    ],
    tool_results={
        "diagram_slice": {"figure": "url", "question": "url"},
        "math_verify": {"status": "ok", "result": "42"}
    },
    reflection_count=1,
    partial_results={"q9": {"verdict": "pending"}}
)
```

**常见错误**：
- `slice_urls` 写成 list（应为 dict）
- `plan_history` 写成字符串（应为 list[dict]）
- `tool_results` 写成单一字符串（应为 dict）

### 2.10 output_key 读写模式（必须）

```python
def _plan(self, state: SessionState) -> dict:
    plan_json = self.planner.run(state)
    state.plan_history.append({
        "iteration": state.reflection_count + 1,
        "plan": plan_json.get("plan", []),
        "timestamp": datetime.utcnow().isoformat()
    })
    return plan_json

def _reflect(self, state: SessionState) -> dict:
    current_plan = state.plan_history[-1] if state.plan_history else {}
    reflection = self.reflector.run(state, current_plan=current_plan)
    state.partial_results["reflection"] = reflection
    return reflection
```

### 2.11 uncertain 判定规则（必须）

**存储规则**：
- `results`：包含所有题目（correct/incorrect/uncertain）
- `wrong_items`：仅包含 `verdict == "incorrect"` 的题目
- `uncertain_items`（可选）: 仅用于前端展示“待确认”

**统计规则**：
```
total = len(results)
correct = count(verdict == "correct")
incorrect = count(verdict == "incorrect")
uncertain = count(verdict == "uncertain")
```

**前端展示规则**：
- `incorrect`：红色叉，展开 judgment_basis
- `correct`：绿色勾，默认折叠
- `uncertain`：黄色问号，显示 warnings

### 2.12 Timeout 策略（验证阶段）
- 先放宽 `AUTONOMOUS_AGENT_TIMEOUT_SECONDS`（建议 300-600s）确保 Loop 能跑通
- 通过 smoke test 后逐步收紧

### 2.13 Rate Limit 处理（P1）
- 遇到 429/TPM 限流时，执行指数退避（1s → 2s → 4s）
- 超过最大重试次数后返回 error 并记 warning

### 2.14 Token 预算优化（P2）
- Planner/Reflector 仅发送“最近一轮 plan + 关键 tool_results”
- plan_history 过长时，仅保留摘要（不超过 N 条）

### 2.15 Confidence 阈值校准（P2）
- 收集 `confidence` 分布与 loop 次数指标
- 每周回放 10-20 样本，更新阈值建议

---

## 3. 迁移与验证

### 3.1 迁移策略（直接替换）

- 直接替换 `/grade` pipeline 为 AutonomousAgent
- 删除旧 pipeline 调用路径
- 回滚方式：回退到上一稳定版本（Git revert），不保留 fallback code

### 3.2 验证指标

- 正确率 / 不确定率 / 误判率
- P50 / P95 延迟
- JSON 修复率
- Loop 平均迭代次数

---

## 4. 测试计划

新增测试目录：`homework_agent/tests/test_autonomous_agent/`

- `test_planner.py`
- `test_executor.py`
- `test_reflector.py`
- `test_aggregator.py`
- `test_tool_diagram_slice.py`
- `test_tool_math_verify.py`
- `test_session_state.py`

集成测试：
- `test_autonomous_agent_e2e.py`

---

## 5. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| Loop 多轮导致超时 | 60s 以上 | 默认 async + SSE 进度提示 |
| JSON 结构失败 | 批改中断 | Aggregator 修复 + 重试 |
| 工具调用失败 | 结果不完整 | Executor 统一重试 + 降级 |

---

## 6. 输出契约（保持不变）

- `/grade` 响应字段不变
- 重点保证：`wrong_items` + `judgment_basis` + `vision_raw_text`

---

## 7. 交付验收

- 单元测试通过
- demo 跑通
- 结果格式与 UI 展示一致
- 日志可回放（plan/tool/reflect/finalize）
