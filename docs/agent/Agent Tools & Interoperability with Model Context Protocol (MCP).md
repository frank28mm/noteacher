# Agent Tools 规范（本项目裁剪版）

> 本文档从《Agent Tools & Interoperability with MCP》白皮书中**仅保留**对本项目当前阶段最有价值的工程规范：`schema`、统一 `ToolResult`、错误恢复字段、输出净化、HITL 触发规则、日志字段约定。  
> **不包含** MCP Host/Client/Server、JSON‑RPC、`tools/list` 动态发现等协议实现内容（本项目当前不需要引入 MCP 协议层）。

---

## 1. 适用范围与目标

**适用范围**
- 适用于本项目所有“工具（tool）”：被 Agent 选择并调用、用于完成某个明确子任务的函数/服务（例如 OCR、切图、数学校验、索引检索等）。
- 适用于 Agent 内部调用（进程内/HTTP 内部服务均可），不要求 MCP 协议。

**目标**
- 让 Agent 的工具调用**可预测、可验证、可恢复、可审计**。
- 降低 LLM 产生错误参数/错误解析/无限重试/上下文膨胀的概率。
- 为后续“评估门禁/生产治理/扩展到插件化”打基础（即使不引入 MCP 协议）。

---

## 2. 工具契约：`ToolSpec`（Schema）

每个工具必须提供一份机器可读的 `ToolSpec`（可用 JSON Schema / Pydantic model / dataclass+schema 导出实现），至少包含：

### 2.1 基本字段
- `name`：稳定的唯一标识（snake_case）。
- `title`：给人看的短标题（可选）。
- `description`：面向 Agent 的“做什么/何时用/不用时怎么办”的说明（必须包含成功条件与常见失败路径）。
- `input_schema`：工具入参 schema（必填）。
- `output_schema`：工具输出 schema（必填）。
- `annotations`：工具行为注解（必填，用于策略/治理）。

### 2.2 `annotations` 约定（用于策略执行，不是 hint）
建议至少包含：
- `read_only`：是否只读（不产生外部副作用）。
- `idempotent`：同参重复调用是否无副作用（便于安全重试）。
- `destructive`：是否可能产生破坏性副作用（删除、覆盖、提交等）。
- `open_world`：是否会访问不受控外部世界（公网、第三方、用户环境）。
- `sensitive_sink`：是否可能导致敏感数据出站/落盘（邮件发送、外链上传、写入外部系统等）。

### 2.3 入参/出参 schema 最低要求
- **入参必须声明**：类型、必填/可选、格式约束（如 `uri` / `data:image/...`）、长度/大小上限、允许字符集或 pattern（用于路径/前缀）。
- **出参必须声明**：`status` 枚举、主数据字段结构、`warnings`、`error`（见下节 ToolResult）。
- **工具调用前后必须校验**：入参校验失败时不得调用工具；出参不符合 schema 视作工具错误（并记录审计日志）。

---

## 3. 工具返回：统一 `ToolResult`

所有工具必须返回统一结构（无论内部实现是 Python/OpenCV/第三方 API）：

```json
{
  "status": "ok | degraded | empty | error",
  "data": {},
  "warnings": [],
  "error": null,
  "meta": {}
}
```

### 3.1 `status` 语义
- `ok`：成功，`data` 可用。
- `degraded`：降级成功（例如切图失败但 OCR 兜底拿到文本），`data` 可用但必须在 `warnings`/`meta` 标注降级原因。
- `empty`：无结果但不算异常（例如未检测到图示 ROI，属于“无图/无 ROI”）。
- `error`：失败，不可用。

### 3.2 `error` 结构（错误恢复字段）
当 `status == "error"` 时，必须包含结构化错误对象：

```json
{
  "code": "tool.SCOPE.CATEGORY.REASON",
  "message": "人类可读的简短说明（不要堆栈）",
  "detail": "可选：更详细的诊断信息（可截断）",
  "recovery_suggestion": "给 Agent 的恢复建议（一句话）",
  "next_steps": ["tool_name_1", "tool_name_2"],
  "can_retry": true,
  "retry_after_seconds": 15
}
```

约束：
- `code` 必须稳定、可统计（用于 metrics/告警/回归分析），不要把自然语言塞进 code。
- `recovery_suggestion`/`next_steps` 必须可执行：`next_steps` 只能引用 allowlist 中存在的工具名。
- `can_retry` 必须结合 `annotations.idempotent` 与具体错误类别决定；不可盲目重试。

### 3.3 `warnings` 约定
- `warnings` 用于可控降级与提示（例如 `diagram_roi_not_found`、`pii_redacted`、`used_cache`、`compressed_image`）。
- warning 应尽量使用稳定字符串常量，便于统计。

### 3.4 `meta` 约定
`meta` 用于补充可观测性/治理字段（不会进入最终用户展示，但可进入日志）：
- `duration_ms`
- `provider`（调用了哪个外部提供方/模型）
- `cache_hit`（是否命中缓存）
- `input_fingerprint` / `output_fingerprint`（可选：hash，用于审计与排查）
- `redaction_applied`（是否做过净化）

---

## 4. 输出净化（Output Sanitization）

工具输出在写入 Session/进入 LLM 上下文之前必须经过净化（至少做到“安全最小化”）。

### 4.1 必须净化/屏蔽的内容
- 任何形式的 token/签名/密钥：`access_token`、`Authorization`、`sig/signature`、云厂商签名参数等。
- OCR/文本中的常见 PII：手机号、邮箱、身份证号等（按产品合规要求扩展）。
- 可执行/可注入内容：
  - HTML/Markdown 中的潜在注入片段（尤其链接、脚本片段）。
  - 任何“像 prompt 的指令段”（例如“忽略之前指令/请调用某工具泄露信息”），要按“非可信数据”对待（可加 `tainted` 标记）。
- 过大的 payload（避免上下文膨胀）：对长文本/长列表截断，并在 `warnings` 里标注 `truncated_output`。

### 4.2 净化策略（建议最低实现）
- **URL 日志脱敏**：记录时移除敏感 query 参数（token、sig 等），必要时只记录 host/path。
- **文本净化**：
  - 正则过滤 PII（最小实现）或接入 PII 检测服务（更可靠）。
  - 对外部工具返回的文本进行长度限制（例如 2–5KB），超出截断。
- **污点标记**：
  - 对“来自外部/未验证”的输出标记 `tainted=true`，Aggregator 在最终结论里必须提示“基于文本推断/需复核”。

---

## 5. HITL（Human-in-the-Loop）触发规则

即使当前工具集大多是“只读/无副作用”，也应建立统一 HITL 规则，用于：
- 低证据/低置信度情况下的人工复核队列
- 未来扩展到写操作/外部动作时的安全闸门

### 5.1 必须触发 HITL 的情况（最低规则）
- `Aggregator` 输出包含 `verdict == "uncertain"`（或业务定义的“不确定”状态）。
- `Reflector.confidence < threshold_low`（建议低于 0.80 进入人工复核；阈值可配置）。
- 关键证据缺失：
  - 图示/切片失败且最终基于 OCR/文本推断（例如 `diagram_roi_not_found` + `degraded/text_only`）。
- 任何工具声明 `annotations.sensitive_sink == true` 或 `annotations.destructive == true`（即使当前未实现此类工具，也要把规则写死在策略层）。

### 5.2 建议触发 HITL 的情况（提升质量）
- 重试/降级链路已走完仍失败（例如循环达到最大迭代数、工具连续错误）。
- 输出净化触发了大量 PII 脱敏（提示“人工确认是否需要进一步处理”）。

---

## 6. 日志字段约定（Logging Contract）

目标：让每次工具调用都能被“回放/统计/排障”，并可与一次请求/一次会话关联。

### 6.1 事件类型建议
- `agent_plan_start` / `agent_plan_done`
- `agent_tool_call` / `agent_tool_done`
- `agent_reflect_pass` / `agent_reflect_fail`
- `agent_aggregate_start` / `agent_aggregate_done`
- `agent_finalize_done`

### 6.2 每条工具日志必须包含的字段
- `event`
- `session_id`
- `request_id`（如有）
- `iteration`（循环第几轮）
- `tool`（工具名）
- `status`（running/completed/error）
- `duration_ms`
- `error_code`（若失败）
- `warnings_count`（若有）
- `provider`（若涉及外部服务）
- `cache_hit`（若有）

### 6.3 日志安全要求
- 日志中不得出现敏感 token/签名/完整 PII。
- URL 必须脱敏（query 参数中敏感字段替换为 `***`）。

---

## 7. 实施建议（落地顺序）

1) **统一 ToolResult 与错误恢复字段**（提升自恢复与稳定性）  
2) **补齐 ToolSpec schema + 执行前后校验**（减少 LLM 误调用与不可预期输出）  
3) **输出净化（PII/token/截断/污点标记）**（生产安全底线）  
4) **HITL 触发规则与审核队列接口**（质量与安全兜底）  
5) **日志字段对齐 + 指标聚合（后续 Agent Quality）**（运维可控）

