# Alerts & SLOs（P2）

> 目标：把“Observe → Act → Evolve”落到可执行的告警/阈值与排障入口上。  
> 说明：本仓库当前不绑定 Prometheus/Grafana/OTel 的具体部署形态；先提供**指标口径 + 告警规则草案 + 运行手册**，后续可接入任意平台。

## 1. 指标口径（当前实现）

### 1.1 HTTP
- `http_requests_total{path,method,status}`：请求计数
- `http_request_duration_seconds_bucket{path,method,le}`：请求耗时直方图（Prometheus 风格）

### 1.2 LLM 成本
- `llm_tokens_total{provider,model,stage}`：token 总量累积（来自 `log_llm_usage`）

## 2. 建议告警（草案）

### P0/P1：强烈建议
- **5xx 错误率突增**：`rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05`
- **关键接口 p95 延迟异常**：基于 `http_request_duration_seconds_bucket` 计算 p95 > 10s（按 `/api/v1/grade`、`/api/v1/chat` 单独阈值）

### P2：规模化时启用
- **LLM tokens 异常飙升**：`rate(llm_tokens_total[15m])` 高于过去 7 天同时间段基线（或阈值）
- **needs_review 占比异常**：用离线/在线指标口径计算（目前主要在日志与评估汇总里）

## 3. 运行入口

- `/metrics`：Prometheus 文本输出（需要 `METRICS_ENABLED=1`；可选 `METRICS_TOKEN` + `X-Metrics-Token`）
- CI artifact：`qa_metrics/`（含 `metrics_summary.json`、`report.html`、`weekly.html`）

