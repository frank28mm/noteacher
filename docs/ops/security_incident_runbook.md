# Security Incident Runbook（P2）

> 目标：把安全事件处理变成可执行流程（发现→止血→修复→复盘→扩充评测集）。

## 1. 触发条件（示例）
- 日志中出现 `pii_detected` / `prompt_injection`（或 `needs_review` 激增）
- 发现 secrets/URL token/PII 被写入日志或持久化
- 外部举报：错误提示泄露系统指令/内部信息

## 2. 立即止血（0-30 分钟）
1. **阻断入口**：临时关闭相关 endpoint 或强制返回 `needs_review`（feature flag/配置开关）
2. **降低风险面**：
   - 关闭可选工具调用（如有）
   - 降低并发（`MAX_CONCURRENT_*`）
3. **证据保全**：
   - 记录 `request_id/session_id`（必填）
   - 保存相关日志片段（脱敏后）

## 3. 定位与修复（30 分钟 - 1 天）
1. 用 `request_id` 聚合链路日志，确认来源：输入/工具输出/LLM 输出/持久化
2. 修复点位（优先硬规则与净化）：
   - 输入侧注入拦截
   - 输出/持久化净化
   - HITL 触发更严格
3. **回收为评测**：
   - 用 `scripts/extract_replay_candidates.py` 提取候选
   - 补充 replay 样本与断言（先结构/安全，再 correctness）

## 4. 复盘（Postmortem）
- 使用 `docs/ops/postmortem_template.md`

