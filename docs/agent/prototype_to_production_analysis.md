# Prototype to Production 原型到生产分析报告

## 概述

本文档基于 Google 的《Prototype to Production》白皮书，结合"作业检查大师"项目的当前实现，系统性地梳理从原型到生产的核心要素，并将其整理为**开发规则**和**开发需求**。

**分析日期**: 2025年12月

**文档来源**: `docs/agent/Prototype to Production.md`

**核心理念**: **"Build an agent is easy. Trusting it is hard."** (构建Agent容易，信任Agent困难)

---

## 一、文档核心价值与指导意义

### 1.1 "最后一公里"问题

文档指出，在Agent系统中，**约80%的工作量**不是在核心智能上，而是在基础设施、安全和验证上。

**现实场景警示**:
- 客服Agent被欺骗免费赠送产品
- 用户通过Agent访问机密数据库
- Agent周末产生巨额账单却无人知晓
- 昨天正常的Agent今天突然失效

### 1.2 Agent系统的独特挑战

| 挑战 | 说明 | 项目现状 |
|------|------|----------|
| **动态工具编排** | Agent每次执行路径不同，需要版本控制和可观测性 | ⚠️ 部分实现（有日志，缺版本控制） |
| **可扩展状态管理** | Session和Memory需要在规模上安全和一致 | ⚠️ 基础实现（SessionState，缺Memory系统） |
| **不可预测的成本/延迟** | 成本和响应时间难以预测，需要预算和缓存 | ✅ 良好（缓存策略完善） |

### 1.3 三大支柱

```
评估 → 部署 → 可观测性
  ↓       ↓        ↓
质量门禁  自动化    数据驱动
```

---

## 二、当前项目评估

### 2.1 预生产成熟度评分

| 领域 | 评分 | 说明 |
|------|------|------|
| **评估体系** | 6/10 | 有Replay Dataset和metrics收集脚本，缺CI门禁 |
| **CI/CD** | 4/10 | 基础CI仅做编译+单元测试，缺评估门禁和CD |
| **安全防护** | 5/10 | 有数学沙箱，缺PII和Prompt Injection防护 |
| **可观测性** | 7/10 | 日志/追踪良好，缺Metrics聚合和Dashboard |
| **版本控制** | 3/10 | 代码有版本，Prompt/Tool/配置缺版本管理 |
| **部署策略** | 2/10 | 无Canary/Blue-Green/Feature Flag |
| **生产运维** | 3/10 | 无告警、无回滚机制、无安全响应手册 |
| **Overall** | **4.3/10** | **原型良好，生产就绪度低** |

### 2.2 现有资产盘点

**优势**:
- ✅ **Replay Dataset** (`homework_agent/tests/replay_data/`): 已有测试样本目录结构
- ✅ **Metrics收集脚本** (`homework_agent/scripts/collect_metrics.py`): 可批量运行并生成P50/P95报告
- ✅ **基础CI** (`.github/workflows/ci.yml`): 有编译和单元测试
- ✅ **Observability基础设施**: `log_event()`, `@trace_span()`；并已具备 `TelemetryCollector`（但当前主链路未接线采集）
- ✅ **缓存策略**: OCR/QIndex/Slice失败缓存
- ⚠️ **Prompt 资产已存在**: `homework_agent/prompts/*.yaml` + `PromptManager`；autonomous prompts 仍主要在代码常量中（`PROMPT_VERSION`）

**劣势**:
- ❌ **评估未自动化**: Replay测试未在CI中运行
- ❌ **无质量门禁**: metrics结果不阻断PR
- ❌ **无CD流程**: 无Staging/Production部署管道
- ❌ **无版本管理**: Prompt/Tool配置变更无追踪
- ❌ **无安全防护**: PII检测和Prompt Injection防护缺失
- ❌ **无生产运维**: 无告警、无回滚、无安全响应流程

---

## 三、开发规则 (长期遵循)

### 规则1: 评估门禁优先 (Evaluation-Gated Deployment)

**原则**: 没有Agent版本应在未通过综合评估前到达用户。

**实施**:
1. **Pre-PR评估**: 提交PR前本地运行评估，报告链接到PR
2. **In-Pipeline门禁**: CI中自动运行评估，失败则阻断部署
3. **评估覆盖**:
   - 行为质量 (Golden Set)
   - 安全合规 (RAI测试)
   - 性能回归 (延迟/成本)

**项目应用**:
```yaml
# .github/workflows/quality_gate.yml (新增)
- name: Run Replay Tests
  run: |
    python3 -m pytest homework_agent/tests/test_replay.py -v

- name: Collect Metrics
  run: |
    python3 homework_agent/scripts/collect_metrics.py \
      --image-dir homework_agent/tests/replay_data/images \
      --mode local \
      --output qa_metrics/metrics.json

- name: Check Regression
  run: |
    python3 scripts/check_baseline.py \
      --current qa_metrics/metrics_summary.json \
      --baseline qa_metrics/baseline.json \
      --threshold 0.05
```

---

### 规则2: 三阶段CI/CD

**原则**: CI/CD是漏斗，尽早捕获错误。

```
Phase 1: Pre-Merge (CI)          → 快速反馈 (单元测试/代码检查/评估套件)
           ↓
Phase 2: Post-Merge (Staging)   → 运行就绪 (负载测试/集成测试/Dogfooding)
           ↓
Phase 3: Gated Production       → 人工审批 (Product Owner批准)
```

**项目应用**:

**Phase 1: CI检查** (现有基础扩展)
```yaml
# .github/workflows/ci.yml (扩展)
jobs:
  test:
    steps:
      - name: Unit Tests        # 现有
        run: pytest -q

      - name: Replay Evaluation # 新增
        run: pytest homework_agent/tests/test_replay.py -v

      - name: Code Quality       # 新增
        run: |
          black --check homework_agent/
          ruff check homework_agent/

      - name: Security Scan      # 新增
        run: bandit -r homework_agent/
```

**Phase 2: Staging验证** (新增)
```yaml
# .github/workflows/cd.yml (新增)
on:
  push:
    branches: [main]

jobs:
  staging:
    steps:
      - name: Deploy to Staging
        run: # 部署到Staging环境

      - name: Integration Tests
        run: pytest tests/integration/ -v

      - name: Load Test
        run: locust -f tests/load_test.py

      - name: Dogfooding Sign-off
        run: # 内部用户测试
```

**Phase 3: 生产部署** (新增)
```yaml
# .github/workflows/production.yml (新增)
on:
  manual_trigger:  # 人工触发

jobs:
  production:
    steps:
      - name: Product Owner Approval
        uses: trstringer/manual-approval@v1

      - name: Deploy to Production
        run: # 使用Canary发布
```

---

### 规则3: 全面版本控制

**原则**: 每个组件都必须版本化，这是生产的"撤销按钮"。

**需要版本化的组件**:
```
✅ 代码               → Git (已有)
❌ Prompt模板         → 缺失
❌ Tool Schema        → 缺失
❌ Model Endpoint     → 缺失
❌ Evaluation Dataset → 缺失
❌ 配置文件           → 缺失
```

**项目应用**:

**方案A: Git Submodule**
```
homework_agent/
├── prompts/          → 作为独立Git仓库
│   ├── .git/
│   ├── math_grader_system.yaml
│   └── english_grader_system.yaml
├── tools/            → 作为独立Git仓库
│   ├── .git/
│   └── schemas/
└── evaluation/       → 作为独立Git仓库
    ├── .git/
    └── golden_sets/
```

**方案B: 配置版本化**
```python
# homework_agent/config/prompts.py
PROMPT_VERSIONS = {
    "math_grader": {
        "v1.0.0": "prompts/v1/math_grader.yaml",
        "v1.1.0": "prompts/v1.1/math_grader.yaml",  # 修复多题处理
        "current": "v1.1.0",
    },
}

# 使用时指定版本
prompt = load_prompt("math_grader", version="v1.0.0")  # 回滚
```

---

### 规则4: 安全从设计开始 (Security by Design)

**原则**: 安全是持续适应过程，不是一次性checklist。

**三层防御**:
```
1. Policy & System Instructions (宪法)
   ↓
2. Guardrails & Filtering (执行层)
   - Input Filtering
   - Output Filtering
   - HITL Escalation
   ↓
3. Continuous Assurance (持续验证)
   - Rigorous Evaluation
   - RAI Testing
   - Red Teaming
```

**项目应用**:

**Input Filtering**
```python
# homework_agent/security/input_filters.py (新增)
class InputFilter:
    def check(self, user_input: str) -> FilterResult:
        # 1. PII检测
        pii_entities = self.pii_detector.detect(user_input)
        if pii_entities:
            return FilterResult(
                safe=False,
                reason="pii_detected",
                entities=pii_entities,
                action="redact_and_proceed"
            )

        # 2. Prompt Injection检测
        if self.injection_detector.detect(user_input):
            return FilterResult(
                safe=False,
                reason="prompt_injection",
                action="block_and_alert"
            )

        return FilterResult(safe=True)
```

**Output Filtering**
```python
# homework_agent/security/output_filters.py (新增)
class OutputFilter:
    def check(self, agent_output: str) -> FilterResult:
        # 1. PII检测
        # 2. 有害内容检测
        # 3. 策略违规检测
        pass
```

---

### 规则5: Observe → Act → Evolve 循环

**原则**: 生产运营是持续循环，而非一次性部署。

```
Observe (观察)
  ↓ 日志/追踪/指标
Act (行动)
  ↓ 实时干预/故障排查
Evolve (演进)
  ↓ 根本原因修复/持续改进
  ↓
  回到 Observe
```

**项目应用**:

**Observe: 完善可观测性**
```python
# 确保所有关键事件都有log_event
log_event(logger, "agent_tool_call",
          session_id=session_id,
          request_id=request_id,  # 新增
          tool=tool_name,
          iteration=iteration,    # 新增
          user_id=user_id,        # 新增
          status="running")

# 确保Telemetry数据被收集
telemetry_collector.record_run(AutonomousAgentTelemetry(...))
```

**Act: 实时干预机制**
```python
# homework_agent/ops/circuit_breaker.py (新增)
class CircuitBreaker:
    """熔断器: 自动禁用失败的工具"""
    def __init__(self, failure_threshold: int = 5):
        self.failure_count = {}
        self.failure_threshold = failure_threshold

    def call_tool(self, tool_name: str, *args, **kwargs):
        if self.is_open(tool_name):
            raise CircuitBreakerOpen(f"Tool {tool_name} is disabled")

        try:
            result = self.call_actual_tool(tool_name, *args, **kwargs)
            self.on_success(tool_name)
            return result
        except Exception as e:
            self.on_failure(tool_name)
            raise

    def is_open(self, tool_name: str) -> bool:
        return self.failure_count.get(tool_name, 0) >= self.failure_threshold
```

**Evolve: 持续改进循环**
```python
# homework_agent/ops/evolution.py (新增)
def evolution_loop():
    # 1. Analyze Production Data
    recent_failures = get_recent_failures(hours=24)

    # 2. Update Evaluation Datasets
    for failure in recent_failures:
        add_to_golden_set(failure)

    # 3. Refine and Deploy
    if improvement_opportunity_detected():
        create_pr_with_fix()
        # CI自动评估
        # CD自动部署
```

---

## 四、开发需求 (按优先级)

### P0 - 立即实施 (1-2周)

#### REQ-001: 建立评估门禁

**目标**: 每次代码变更自动检测回归

**实施内容**:

**A. 扩充Replay Dataset**
```bash
# homework_agent/tests/replay_data/images/
# 需要收集:
- 5个简单算术题 (1+1, 2*3, etc.)
- 5个代数题 (x+2=5, etc.)
- 5个几何题 (含图示)
- 3个低OCR质量样本
- 2个多题页样本

# 共20个样本
```

**B. 创建Replay测试**
```python
# homework_agent/tests/test_replay.py (新增)
import pytest
from pathlib import Path

REPLAY_DATA_DIR = Path(__file__).parent / "replay_data"

@pytest.mark.replay
def test_simple_arithmetic():
    """测试简单算术题"""
    image_path = REPLAY_DATA_DIR / "images" / "simple_arithmetic_001.jpg"
    result = run_autonomous_grade_agent(...)
    assert result.status == "done"
    assert any(r["verdict"] == "correct" for r in result.results)

# ... 其他测试用例
```

**C. CI集成**
```yaml
# .github/workflows/quality_gate.yml (新增)
name: Quality Gate

on:
  pull_request:
    branches: [main, dev]

jobs:
  evaluation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run Replay Tests
        run: |
          pytest homework_agent/tests/test_replay.py -v

      - name: Collect Metrics
        run: |
          python3 homework_agent/scripts/collect_metrics.py \
            --image-dir homework_agent/tests/replay_data/images \
            --mode local \
            --limit 20 \
            --output qa_metrics/metrics.json

      - name: Check Regression
        run: |
          python3 scripts/check_baseline.py \
            --current qa_metrics/metrics_summary.json \
            --baseline .github/baselines/metrics_baseline.json \
            --threshold 0.05
```

**验收标准**:
- [ ] Replay Dataset包含20个样本
- [ ] Replay测试可在本地通过
- [ ] CI中自动运行并阻断失败PR

---

#### REQ-002: 贯通关联字段

**目标**: 让Logs/Traces能按同一条任务链路汇总

**实施内容**:

**A. request_id传播**
```python
# homework_agent/services/autonomous_agent.py (修改)

@trace_span("autonomous_agent.run")
async def run_autonomous_grade_agent(
    *,
    images: List[ImageRef],
    subject: Subject,
    provider: str,
    session_id: str,
    request_id: Optional[str],  # 确保传入
) -> AutonomousGradeResult:
    # 生成request_id (如果未提供)
    if not request_id:
        request_id = f"{session_id}_{int(time.time())}"

    # 所有log_event都携带request_id
    log_event(logger, "agent_start",
              session_id=session_id,
              request_id=request_id,
              image_count=len(images))

# ExecutorAgent.run() 中添加request_id
log_event(executor_logger, "agent_tool_call",
          session_id=state.session_id,
          request_id=request_id,  # 从外部传入
          tool=tool_name,
          status="running",
          iteration=state.reflection_count + 1)
```

**B. Token/Usage打点**
```python
# homework_agent/utils/observability.py (新增)
def log_llm_usage(logger, *, request_id: str, session_id: str,
                  model: str, provider: str, usage: dict, **kwargs):
    """记录LLM使用情况"""
    log_event(logger, "llm_usage",
              request_id=request_id,
              session_id=session_id,
              model=model,
              provider=provider,
              prompt_tokens=usage.get("prompt_tokens", 0),
              completion_tokens=usage.get("completion_tokens", 0),
              total_tokens=usage.get("total_tokens", 0),
              **kwargs)

# 在LLM调用后记录
text = await _call_llm_with_backoff(...)
log_llm_usage(planner_logger,
              request_id=request_id,
              session_id=session_id,
              model="doubao-pro-32k",
              provider=provider,
              usage=text.usage if hasattr(text, 'usage') else {})
```

**C. 失败模式统一**
```python
# homework_agent/utils/error_codes.py (新增)
ERROR_CODES = {
    # Parse failures
    "PARSE_FAILED": "parse_failed",
    "TOOL_PARSE_FAILED": "tool_parse_failed",
    "AGGREGATOR_PARSE_FAILED": "aggregator_parse_failed",

    # Tool failures
    "TOOL_ERROR": "tool_error",
    "TOOL_TIMEOUT": "tool_timeout",
    "TOOL_DEGRADED": "tool_degraded",

    # Agent exits
    "MAX_ITERATIONS_REACHED": "max_iterations_reached",
    "CONFIDENCE_NOT_MET": "confidence_not_met",

    # Safety
    "PII_DETECTED": "pii_detected",
    "PROMPT_INJECTION": "prompt_injection",
    "NEEDS_REVIEW": "needs_review",
}

WARNING_CODES = {
    "DIAGRAM_SLICE_FAILED": "diagram_slice_failed",
    "OCR_FALLBACK": "ocr_fallback",
    "VISION_ROI_NOT_FOUND": "vision_roi_not_found",
    "FIGURE_TOO_SMALL": "figure_too_small",
}

# 使用
log_event(logger, "agent_error",
          error_code=ERROR_CODES["PARSE_FAILED"],
          error_details=...)
```

**验收标准**:
- [ ] 所有log_event都有request_id
- [ ] LLM usage被记录
- [ ] 错误/警告有统一code

---

#### REQ-003: 基础安全防护

**目标**: 阻止明显的安全风险

**实施内容**:

**A. PII检测**
```python
# homework_agent/security/pii_detector.py (新增)
import re
from typing import List, Tuple

PII_PATTERNS = {
    "chinese_id": r"\b[1-9]\d{5}(18|19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b",
    "chinese_phone": r"\b1[3-9]\d{9}\b",
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
}

class PIIDetector:
    def __init__(self):
        self.compiled_patterns = {
            name: re.compile(pattern)
            for name, pattern in PII_PATTERNS.items()
        }

    def detect_and_redact(self, text: str) -> Tuple[str, List[dict]]:
        """检测并脱敏PII"""
        found = []
        for name, pattern in self.compiled_patterns.items():
            for match in pattern.finditer(text):
                found.append({
                    "type": name,
                    "start": match.start(),
                    "end": match.end(),
                    "value": match.group(),
                })

        # 脱敏
        redacted = text
        for entity in reversed(found):  # 从后向前替换，保持位置
            start, end = entity["start"], entity["end"]
            redacted = redacted[:start] + f"[{entity['type'].upper()}]" + redacted[end:]

        return redacted, found
```

**B. Prompt Injection检测**
```python
# homework_agent/security/prompt_guard.py (新增)
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous\s+)?instructions",
    r"disregard\s+(all\s+)?(previous\s+)?(prompt|instructions)",
    r"系统指令|忽略.*指令|越狱",
]

class PromptGuard:
    def __init__(self):
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in INJECTION_PATTERNS
        ]

    def check(self, user_input: str) -> dict:
        """检测Prompt Injection"""
        for pattern in self.compiled_patterns:
            if pattern.search(user_input):
                return {
                    "safe": False,
                    "reason": "prompt_injection",
                    "matched_pattern": pattern.pattern,
                }
        return {"safe": True}
```

**C. 集成到Agent**
```python
# homework_agent/services/autonomous_agent.py (修改)

async def run_autonomous_grade_agent(...) -> AutonomousGradeResult:
    # ... existing code ...

    # 新增: 安全检查
    from homework_agent.security.pii_detector import PIIDetector
    from homework_agent.security.prompt_guard import PromptGuard

    pii_detector = PIIDetector()
    prompt_guard = PromptGuard()

    # 检查OCR文本中的PII
    if state.ocr_text:
        redacted_ocr, pii_entities = pii_detector.detect_and_redact(state.ocr_text)
        if pii_entities:
            log_event(logger, "pii_detected",
                      session_id=session_id,
                      request_id=request_id,
                      count=len(pii_entities),
                      types=[e["type"] for e in pii_entities])
            state.warnings.append("PII_DETECTED")
            # 使用脱敏后的文本
            state.ocr_text = redacted_ocr

    # 注意: 不改变Planner的action，只添加标记
    # 让后续Aggregator知道需要人工复核
```

**验收标准**:
- [ ] PII检测覆盖率>90%
- [ ] Prompt Injection检测不误报
- [ ] 安全检查不破坏现有状态机

---

### P1 - 短期规划 (2-4周)

#### REQ-004: Metrics Dashboard

**目标**: 可视化系统健康和质量指标

**实施内容**:

**A. 简化版Dashboard (离线优先)**
仓库已内置 `scripts/generate_metrics_report.py`，将 `metrics_summary.json` 转成可直接打开的 HTML：
```bash
python3 scripts/generate_metrics_report.py \
  --input qa_metrics/metrics_summary.json \
  --output qa_metrics/report.html
```

**B. Prometheus 导出器（可选，P2+）**：等你们确定要做在线监控（Prometheus/Grafana/OTel）时再补；P1 先用离线 `metrics_summary.json` + HTML 报表即可。

**验收标准**:
- [ ] 可生成HTML报告
- [ ] （可选）可导出 Prometheus metrics

---

#### REQ-005: CD流程

**目标**: 建立Staging → Production部署流程

**实施内容**:
当前仓库尚未确定部署形态（也没有 Dockerfile / docker-compose / K8s manifests），建议先把“流程规则”定清楚：
- **Phase 1（P1）**：能一键部署到 staging（先手工也行），并且有 smoke test + 手工审批（HITL）入口。
- **Phase 2（P2）**：再决定具体形态（Docker / Serverless / K8s / 平台化），把部署脚本与回滚脚本固化到仓库。
- **最小回滚策略（从第一天就可用）**：`git revert` + 走同一条流水线重新部署（不依赖具体平台命令）。

**验收标准**:
- [ ] 有清晰的 staging 部署方式（命令/脚本/文档之一）
- [ ] 有 smoke test（或最小 replay 回归）可验证
- [ ] 有平台无关的回滚步骤（`git revert` + redeploy）

---

#### REQ-006: Prompt版本管理

**目标**: Prompt变更可追溯、可回滚

**实施内容**:
以当前仓库实现为准（`homework_agent/utils/prompt_manager.py` + `homework_agent/prompts/*.yaml`）：
- **P0（立刻可执行）**：每次修改 `homework_agent/prompts/*.yaml` 必须递增 `version`，并在 PR 说明变更目的与风险。
- **P0（可审计）**：运行时日志必须记录 `prompt_id` + `prompt_version`（以及 `provider/model`），用于回放与定位回归。
- **回滚**：优先通过 `git revert` 回到上一个 prompt 版本；后续再引入“运行时选择版本/灰度”的 registry（P2+）。

**验收标准**:
- [ ] Prompt 变更有明确版本号（`version`）且可追溯（PR/commit）
- [ ] 线上/离线日志能关联到使用的 prompt 版本
- [ ] 可通过 `git revert` 回滚 prompt 变更

---

### P2 - 长期规划 (1-2月)

#### REQ-007: 生产运维能力

**目标**: 完善的生产运营能力

**实施内容**:

**A. 告警系统**
```python
# homework_agent/monitoring/alerts.py (新增)
from dataclasses import dataclass
from typing import List

@dataclass
class Alert:
    name: str
    condition: str
    threshold: float
    severity: str  # "critical", "warning", "info"

ALERT_RULES = [
    Alert("HighLatency", "p99_latency_ms", 30000, "critical"),
    Alert("LowSuccessRate", "success_rate", 0.85, "warning"),
    Alert("HighErrorRate", "error_rate", 0.05, "critical"),
    Alert("CostOverBudget", "daily_cost_usd", 100, "warning"),
]

class AlertManager:
    def check_alerts(self, metrics: dict) -> List[Alert]:
        """检查告警规则"""
        triggered = []
        for rule in ALERT_RULES:
            value = metrics.get(rule.condition, 0)
            if rule.condition.endswith("_rate"):
                # 对于比率，低于阈值为问题
                if value < rule.threshold:
                    triggered.append(rule)
            else:
                # 对于绝对值，高于阈值为问题
                if value > rule.threshold:
                    triggered.append(rule)
        return triggered

    def send_alert(self, alert: Alert, metrics: dict):
        """发送告警"""
        # 发送到钉钉/企业微信/邮件
        pass
```

**B. 回滚机制**
```python
# homework_agent/ops/rollback.py (新增)
class RollbackManager:
    def __init__(self):
        self.deployment_history = []

    def deploy(self, version: str):
        """部署指定版本"""
        # 记录部署
        self.deployment_history.append({
            "version": version,
            "timestamp": time.time(),
            "status": "deployed",
        })

    def rollback(self, to_version: str = None):
        """回滚到指定版本"""
        if to_version is None:
            # 回滚到上一个稳定版本
            to_version = self._get_last_stable_version()

        # 执行回滚
        self.deploy(to_version)
        log_event(logger, "rollback",
                  from_version=self._get_current_version(),
                  to_version=to_version)
```

**C. 安全响应手册**
```markdown
# docs/security_response_playbook.md (新增)

## 安全响应流程

### 1. Containment (立即遏制)
- 触发熔断器: 禁用受影响的工具
- 路由可疑请求到HITL队列
- 降低流量: 限流或停服

### 2. Triage (分类)
- 分析攻击范围和影响
- 确定攻击类型
- 记录到安全事件日志

### 3. Resolution (解决)
- 开发补丁: 更新filter/prompt
- 部署修复: 通过CI/CD
- 更新评估集: 添加新攻击样本

### 常见攻击类型

#### Prompt Injection
**症状**: Agent执行非预期操作
**响应**:
1. 立即禁用受影响的工具
2. 添加到Injection检测规则
3. 更新System Prompt

#### PII泄露
**症状**: 输出包含敏感信息
**响应**:
1. 启用Output Filter
2. 更新PII检测模式
3. 通知受影响用户
```

**验收标准**:
- [ ] 告警规则生效
- [ ] 可快速回滚
- [ ] 安全响应手册完整

---

#### REQ-008: A2A协议准备

**目标**: 为未来多Agent协作做准备

**实施内容**:

**A. Agent Card定义**
```yaml
# .well-known/agent-card.json (新增)
{
  "name": "homework_grader_agent",
  "version": "1.0.0",
  "description": "An AI agent that grades homework assignments",
  "capabilities": {
    "subjects": ["math", "english"],
    "input_formats": ["image"],
    "output_formats": ["json", "text"]
  },
  "securitySchemes": {
    "bearerAuth": {
      "type": "http",
      "scheme": "bearer"
    }
  },
  "defaultInputModes": ["image/jpeg", "image/png"],
  "defaultOutputModes": ["application/json"],
  "skills": [
    {
      "id": "grade_math",
      "name": "Grade Math Homework",
      "description": "Automatically grade math assignments",
      "tags": ["math", "grading", "education"]
    },
    {
      "id": "grade_english",
      "name": "Grade English Homework",
      "description": "Automatically grade English assignments",
      "tags": ["english", "grading", "education"]
    }
  ],
  "url": "https://api.example.com/a2a/homework_grader"
}
```

**B. A2A端点 (预留)**
```python
# homework_agent/api/a2a.py (新增，暂时仅定义)
from fastapi import APIRouter

router = APIRouter(prefix="/a2a", tags=["A2A"])

@router.post("/grade")
async def a2a_grade(request: A2AGradeRequest):
    """
    A2A协议端点: 供其他Agent调用

    注意: 当前版本未实现，仅预留接口
    """
    raise NotImplementedError("A2A protocol not yet implemented")

@router.get("/.well-known/agent-card.json")
async def get_agent_card():
    """返回Agent Card"""
    import json
    from pathlib import Path
    card_path = Path(".well-known/agent-card.json")
    return json.loads(card_path.read_text())
```

**验收标准**:
- [ ] Agent Card定义完成
- [ ] A2A端点预留
- [ ] 文档说明未来扩展路径

---

## 五、实施路线图

### Phase 1: 基础评估与安全 (2周)

| 需求 | 优先级 | 工作量 | 产出 |
|------|--------|--------|------|
| REQ-001: 评估门禁 | P0 | 3天 | Replay Dataset + CI门禁 |
| REQ-002: 关联字段 | P0 | 2天 | request_id传播 + Token打点 |
| REQ-003: 安全防护 | P0 | 3天 | PII检测 + Prompt Injection防护 |

**验收标准**:
- [ ] PR必须通过Replay评估
- [ ] 所有log_event有request_id
- [ ] PII检测覆盖率>90%

---

### Phase 2: CI/CD与监控 (2周)

| 需求 | 优先级 | 工作量 | 产出 |
|------|--------|--------|------|
| REQ-004: Metrics Dashboard | P1 | 3天 | HTML报告 + Prometheus导出器 |
| REQ-005: CD流程 | P1 | 4天 | Dockerfile + Staging部署 |
| REQ-006: Prompt版本管理 | P1 | 2天 | Prompt配置 + 加载器 |

**验收标准**:
- [ ] 可生成Metrics报告
- [ ] 可部署到Staging
- [ ] Prompt可追溯版本

---

### Phase 3: 生产运维 (2周)

| 需求 | 优先级 | 工作量 | 产出 |
|------|--------|--------|------|
| REQ-007: 生产运维能力 | P2 | 4天 | 告警 + 回滚 + 安全手册 |
| REQ-008: A2A协议准备 | P2 | 2天 | Agent Card + 端点预留 |

**验收标准**:
- [ ] 告警规则生效
- [ ] 可快速回滚
- [ ] A2A接口预留

---

## 六、开发规则速查表

### PR提交前检查清单

```markdown
## 代码审查清单

### 功能
- [ ] 单元测试通过
- [ ] Replay测试通过
- [ ] Metrics无回归

### 可观测性
- [ ] 新函数有@trace_span
- [ ] 关键事件有log_event
- [ ] log_event包含request_id

### 安全
- [ ] PII检测不退化
- [ ] Prompt Injection检测不退化
- [ ] 敏感信息已脱敏

### 文档
- [ ] Prompt版本已更新
- [ ] 变更日志已更新
```

### CI/CD检查清单

```yaml
# Phase 1: CI (Pre-Merge)
- [ ] 编译检查
- [ ] 单元测试
- [ ] Replay评估
- [ ] 代码质量检查
- [ ] 安全扫描

# Phase 2: Staging (Post-Merge)
- [ ] 部署到Staging
- [ ] 集成测试
- [ ] 负载测试
- [ ] 内部用户测试

# Phase 3: Production (Manual)
- [ ] Product Owner批准
- [ ] Canary发布 (1%)
- [ ] 监控指标正常
- [ ] 全量发布
```

### 生产运维检查清单

```markdown
## 日常运维

### Observe
- [ ] 检查Dashboard
- [ ] 查看告警
- [ ] 审查日志

### Act
- [ ] 响应告警
- [ ] 处理incident
- [ ] 触发熔断 (如需要)

### Evolve
- [ ] 分析失败case
- [ ] 更新评估集
- [ ] 创建改进PR

## 安全响应

### Containment
- [ ] 禁用受影响工具
- [ ] 路由到HITL
- [ ] 降低流量

### Triage
- [ ] 分析攻击范围
- [ ] 记录安全事件

### Resolution
- [ ] 开发补丁
- [ ] 部署修复
- [ ] 更新评估集
```

---

## 七、总结

### 核心差距

| 领域 | 当前评分 | 目标评分 | 关键改进 |
|------|----------|----------|----------|
| **评估体系** | 6/10 | 9/10 | CI门禁 + 自动化评估 |
| **CI/CD** | 4/10 | 8/10 | 三阶段流程 + CD自动化 |
| **安全防护** | 5/10 | 8/10 | PII + Injection防护 |
| **可观测性** | 7/10 | 9/10 | Dashboard + 告警 |
| **版本控制** | 3/10 | 8/10 | Prompt/Tool版本管理 |
| **部署策略** | 2/10 | 7/10 | Canary + 回滚 |
| **生产运维** | 3/10 | 8/10 | 告警 + 安全响应手册 |

### 优先级建议

**立即执行 (P0, 1-2周)**:
1. 建立Replay评估门禁
2. 贯通request_id关联字段
3. 实施基础安全防护

**短期规划 (P1, 2-4周)**:
1. Metrics Dashboard
2. CD流程
3. Prompt版本管理

**长期规划 (P2, 1-2月)**:
1. 生产运维能力
2. A2A协议准备

### 设计原则

1. **评估门禁优先**: 不通过评估不部署
2. **三阶段CI/CD**: CI → Staging → Production
3. **全面版本控制**: 代码/Prompt/Tool/配置
4. **安全从设计开始**: 三层防御
5. **Observe-Act-Evolve**: 持续改进循环

---

## 附录A: 参考资料

- Google Prototype to Production白皮书: `docs/agent/Prototype to Production.md`
- 项目Replay Dataset: `homework_agent/tests/replay_data/`
- Metrics收集脚本: `homework_agent/scripts/collect_metrics.py`
- 现有CI配置: `.github/workflows/ci.yml`

---

**文档版本**: v1.0
**最后更新**: 2025年12月
