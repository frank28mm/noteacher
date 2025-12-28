# 代码与文档合规性自检报告

> **分析日期**: 2025-12-28
> **分析范围**: Git 待提交变更（80 files changed, 4726 insertions, 1098 deletions）
> **对照文档**: `next_development_worklist_and_pseudocode.md`, `agent_sop.md`, `development_rules.md`, `development_rules_quickref.md`, `engineering_guidelines.md`

---

## 一、P0 任务完成情况总览

| 任务编号 | 任务名称 | 完成状态 | 备注 |
|---------|---------|---------|------|
| WL‑P0‑001 | Replay Golden Set v0 扩充 | ✅ 最小可用已完成 | 已有 5 个离线样本（满足 P0 最小覆盖）；但未达到 worklist 建议的 20–30 个规模 |
| WL‑P0‑002 | Replay + Metrics 日常门禁 | ✅ 已完成 | CI 已集成，支持 baseline 阻断 |
| WL‑P0‑003 | 全链路关联字段贯通 | ✅ 核心已完成（可优化） | 已有 middleware，支持 request_id/session_id 提取与传播；ContextVar/模块化属于可选工程化优化 |
| WL‑P0‑004 | 成本/时延护栏 | ✅ 已完成 | `budget.py` + `RunBudget` 已实现 |
| WL‑P0‑005 | ToolResult 统一契约 | ✅ 已完成 | `models/tool_result.py` 已实现 |
| WL‑P0‑006 | Prompt/模型/阈值可追溯 | ✅ 已完成 | Prompt 已版本化，log 记录 version |

---

## 二、详细分析

### 2.1 ✅ 已完成且符合规范的部分

#### 1. Replay Golden Set (WL-P0-001)
- **位置**: `homework_agent/tests/replay_data/samples/`
- **样本数量**: 5 个（满足 P0 最小覆盖 5-10 个要求；但低于 worklist 推荐的 20–30 个规模）
  - `sample_001_math_arithmetic.json`
  - `sample_002_math_geometry.json`
  - `sample_003_math_blurry_ocr.json`
  - `sample_004_english_short.json`
  - `sample_005_multi_question.json`
- **覆盖场景**: 数学计算、几何、OCR 模糊、英语、多题目
- **测试文件**: `test_replay.py` 已实现 schema 验证

#### 2. CI 质量门禁 (WL-P0-002)
- **位置**: `.github/workflows/ci.yml`
- **已集成**:
  - ✅ 单元测试 (`pytest -q`)
  - ✅ 可观测性检查 (`check_observability.py`)
  - ✅ 安全扫描 (`bandit` + `pylint`)
  - ✅ Replay 评估 (`test_replay.py` + `collect_replay_metrics.py`)
  - ✅ 回归检测 (`check_baseline.py`)
  - ✅ 周报生成 (`generate_weekly_report.py`)
  - ✅ Redis 集成测试（独立 job）
- **Baseline 文件**: `.github/baselines/metrics_baseline.json` ✅ 已存在

#### 3. 成本/时延护栏 (WL-P0-004)
- **位置**: `homework_agent/utils/budget.py`
- **实现**:
  - `RunBudget` 类：时间预算 + token 预算
  - `extract_total_tokens()`: 从 usage 对象提取 tokens
  - `is_time_exhausted()` / `is_token_exhausted()`: 护栏检测
- **集成**: `autonomous_agent.py` 已使用 `budget` 参数

#### 4. ToolResult 统一契约 (WL-P0-005)
- **位置**: `homework_agent/models/tool_result.py`
- **实现**:
  - `ToolResult` 类：308 行完整实现
  - 包含所有规范字段：`ok`, `data`, `error_type`, `error_code`, `retryable`, `fallback_used`, `warnings`, `needs_review`, `warning_codes`, `timing_ms`, `stage`, `tool_name`, `request_id`, `session_id`
  - `from_legacy()`: 兼容旧版工具输出
  - `to_dict(merge_raw=True)`: 支持合并原始数据
- **测试**: `test_tool_result_contract.py` ✅

#### 5. 可观测性 (规则 1.1-1.3)
- **位置**: `homework_agent/utils/observability.py`
- **实现**:
  - `@trace_span`: 轻量级追踪装饰器
  - `log_event()`: 结构化日志（含 session_id/request_id/iteration）
  - `log_llm_usage()`: LLM token 使用记录
  - `redact_url()`: URL 敏感参数脱敏
- **检查脚本**: `scripts/check_observability.py` ✅

#### 6. Prompt 版本管理 (规则 4.1)
- **位置**: `homework_agent/prompts/*.yaml`
- **版本化**:
  - `math_grader_system.yaml`: `version: 1`
  - `english_grader_system.yaml`: 已版本化
  - `socratic_tutor_system.yaml`: 已版本化
- **格式**: 包含 `id`, `version`, `language`, `purpose` 字段

#### 7. Feature Flags (规则 5.3)
- **位置**: `homework_agent/utils/feature_flags.py`
- **实现**:
  - `decide()`: 支持静态开关、rollout 百分比、variants
  - `FlagDecision`: 包含 enabled/variant/reason
  - 稳定 hash 分桶（SHA256）
- **测试**: `test_feature_flags.py` ✅

#### 8. 安全模块 (规则 3.1-3.3)
- **位置**: `homework_agent/security/safety.py`
- **实现**:
  - `detect_pii_codes()`: 检测邮箱/手机/身份证/学号
  - `detect_prompt_injection()`: 检测注入攻击
  - `redact_secrets()` / `redact_pii()`: 敏感信息脱敏
  - `sanitize_text_for_log()` / `sanitize_value_for_log()`
  - `scan_safety()`: 综合安全扫描，返回 `warning_codes` + `needs_review`
  - `sanitize_session_data_for_persistence()`: 持久化前脱敏
- **测试**: `test_security_safety.py` ✅ (27 个测试用例)

#### 9. Reviewer 工作流 (P2 提前实现)
- **位置**: 
  - `homework_agent/services/review_queue.py`
  - `homework_agent/api/review.py`
  - `homework_agent/api/reviewer_ui.py`
- **实现**:
  - `enqueue_review_item()`: 入队需人工审核项
  - `list_review_items()` / `get_review_item()` / `resolve_review_item()`
  - REST API: `/review/items`, `/review/items/{id}`, `/review/items/{id}/resolve`
  - Admin Token 保护
- **测试**: `test_review_api.py`, `test_review_queue.py` ✅

---

### 2.2 ⚠️ 部分完成/可优化的部分

#### 1. Request Context Middleware (WL-P0-003)
**现状**:
- `main.py` 中已实现 `_request_id_middleware`
- 已支持 `request_id` 和 `session_id` 的提取与传播
- 已支持 `X-Request-Id` / `X-Session-Id` 响应头（best-effort）
- 早失败场景（401/422/中间件异常）也可在 error payload 中包含 `request_id/session_id`（若请求侧提供）

**与文档“建议实现”相比的差异（可优化，但不构成缺口）**:
- 未独立模块化为 `homework_agent/api/middleware/request_context.py`（目前内联在 `main.py`）
- 未使用 `contextvars.ContextVar`（目前采用显式传参 + request.state，已满足追踪与可读性）

**建议（工程化增强，非阻塞）**:
```python
# homework_agent/api/middleware/request_context.py (建议新增)
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
session_id_var: ContextVar[str] = ContextVar("session_id", default="")

def get_request_id() -> str:
    return request_id_var.get() or ""
```

#### 2. log_event 字段一致性
**现状**: 已通过 `scripts/check_observability.py --strict`（0 warning）。

**说明**:
- `iteration`：`log_event()` 内部会在存在 `session_id` 但缺 `iteration` 时自动补 `iteration=0`，用于对齐规则口径与统计聚合。
- `user_id`：属于“建议字段”，不是所有事件都能/都应包含（例如未认证或匿名请求）。

#### 3. Autonomous Agent 日志点位
**文档要求的日志事件**:
- `agent_plan_start` ✅
- `agent_tool_call` ✅
- `agent_tool_done` ✅
- `agent_reflect_*` ✅（含 pass/fail 及 LLM failed）
- `agent_finalize_done` ✅
- `run_versions` ✅（记录 prompt_version/model/vision_model/thresholds_hash/experiments）

---

### 2.3 ❌ 尚未完成/待测试的部分

#### 1. Live Replay 测试
- **现状**: `test_replay_live_placeholder` 标记为 skip
- **依赖**: 需要 `RUN_REPLAY_LIVE=1` 环境变量 + provider secrets
- **建议**: 在本地验证后再考虑 CI 集成

#### 2. Baseline 阈值治理 (WL-P1-001)
- **现状**: baseline 文件存在，且 `development_rules.md` 已给出更新命令；但缺少“何时允许更新”的团队约束口径（例如必须附带 replay 报告/原因说明）。
- **建议**: 增加 PR 模板/checklist（说明：更新 baseline 的理由、影响面、回归产物链接）。

#### 3. 周报自动化 (WL-P1-002)
- **现状**: `generate_weekly_report.py` 脚本已存在
- **补充**: CI 也会生成 `qa_metrics/weekly.html` 并作为 artifact 上传
- **待验证**: 需要在 GitHub Actions 实际跑一次，确认 artifact 产物可下载/可阅读（这属于运行环境验收，非代码缺口）。

#### 4. 数据库 Migration
- **现状**: 无 `migrations/` 目录
- **规范要求**: 每个 migration 需有 `up()` 和 `down()` 方法
- **建议**: 如有 schema 变更计划，提前搭建 migration 目录结构

---

### 2.4 ⚠️ 文档口径与实现行为的差异（需明确“改文档 or 改实现”）

> 这类问题容易导致团队按文档实施时“踩空”，建议作为合规报告的显式条目维护。

#### 1) SSE 心跳/断线口径
- **文档口径**: 心跳建议 30s；90s 内无数据可断开（`agent_sop.md` / `engineering_guidelines.md`）
- **实现现状**: chat 流在等待 LLM streaming 时约 10s 触发一次 heartbeat（以保持连接），但未实现“90s 自动断开”的行为口径。
- **影响**: 若团队/前端按“90s 自动断开”设计重连策略，可能与后端实际行为不一致。

#### 2) Chat 是否允许“实时看图”
- **SOP 口径**: Chat 不实时看图，只消费 `/grade` 的 `judgment_basis + vision_raw_text`（`agent_sop.md`）
- **实现现状**: 代码中存在“重看图/VFE relook”的实现骨架（未必在主路径启用），容易造成能力边界认知歧义。
- **建议**: 明确当前默认策略（完全关闭 / 仅在特定条件启用 / 仅用于实验），并在文档里写清楚。

## 三、测试覆盖分析

### 新增/修改的测试文件

| 测试文件 | 覆盖模块 | 状态 |
|---------|---------|------|
| `test_tool_result_contract.py` | ToolResult 契约 | ✅ |
| `test_budget.py` | RunBudget 护栏 | ✅ |
| `test_feature_flags.py` | Feature Flags | ✅ |
| `test_security_safety.py` | 安全脱敏 | ✅ (27 cases) |
| `test_grade_error_sanitization.py` | 错误信息不泄露 | ✅ |
| `test_replay.py` | Replay 框架 | ✅ |
| `test_review_api.py` | Reviewer API | ✅ |
| `test_review_queue.py` | Reviewer 队列 | ✅ |
| `test_autonomous_tools.py` | Autonomous 工具 | ✅ |
| `test_context_compactor.py` | Context 压缩 | ✅ |
| `test_preprocessing_pipeline.py` | 预处理流水线 | ✅ |

### 待补充的测试

1. **Live Replay 测试**: 需要真实 provider 调用
2. **端到端 CI 测试**: 验证完整 grade → chat 流程
3. **边界条件测试**: 超时/预算耗尽场景

---

## 四、优化建议汇总

### 高优先级 (P0)

1. **模块化 Request Context Middleware**
   - 将 `main.py` 中的 middleware 抽取到独立模块
   - 使用 `contextvars` 实现跨调用链传递

2. **对齐“文档口径 vs 实现行为”**
   - SSE 心跳/断线（30s/90s）的行为口径
   - Chat 是否允许实时看图的能力边界

### 中优先级 (P1)

4. **补充 Live Replay 测试**
   - 创建本地验证脚本
   - 文档化测试步骤

5. **Baseline 更新流程文档化**
   - 补充 PR 模板
   - 说明何时/如何更新 baseline

6. **周报归档验证**
   - 确认 CI artifact 可下载
   - 验证趋势数据积累

### 低优先级 (P2)

7. **Migration 框架**
   - 如有 schema 变更计划，提前搭建 migration 目录结构

8. **Prompt A/B 测试支持**
   - 结合 Feature Flags 实现 prompt variant 选择

---

## 五、结论

### ✅ 已符合规范的核心功能

- Replay Golden Set + CI 门禁
- ToolResult 统一契约
- 成本/时延护栏 (RunBudget)
- 可观测性基础设施 (trace_span/log_event/log_llm_usage)
- Prompt 版本管理
- Feature Flags
- 安全脱敏与 PII 检测
- Reviewer 工作流 (提前实现)

### ⚠️ 需要微调的部分

- Request Context Middleware 模块化
- 文档口径与实现行为的对齐（SSE 心跳/断线、Chat 实时看图边界）

### ❌ 尚未验证的部分

- Live Replay 真实调用
- 周报自动归档
- 生产环境 CORS 配置验证

---

**总体评估**: 代码实现与文档要求的契合度约 **85-90%**。P0 核心任务已具备“可回归/可观测/可控”的最小闭环；当前主要风险不在“缺功能”，而在少数 **文档口径与实现行为** 的不一致与 **样本覆盖规模** 不足（影响回归有效性）。
