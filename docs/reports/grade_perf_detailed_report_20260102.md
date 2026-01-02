# /grade 性能与质量详细工程复盘（URL-only 快路径）

> 面向工程对齐：本报告用于与其他工程师核对“现象 → 根因 → 实验 → 代码落地 → 可复现证据 → 后续计划”。
>
> 唯一执行计划入口：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑A）

## 0) 背景与目标

**背景现象**：同一张作业图在我们的 Demo/bench 中出现“分钟级甚至更久”的耗时，与豆包 App “10~20 秒出结果”差距很大；同时我们的目标是“可审计/可解释/可降级”，不能只追求快。

**本轮目标**（先跑稳）：

- `/grade` 在 Demo 场景可稳定跑通（不再“questions_count=1 + parse_failed”）
- 把快路径（无图形切片、无图形证据）压到可用区间：**p50 < 60s / p95 < 120s**（无排队干扰）
- 每次结果携带可审计证据：`timings_ms` + `ark_response_id`（可用 Ark GET 接口回查）

## 1) 关键结论（当前推荐默认）

**推荐默认（当前）**：

- `AUTONOMOUS_PREPROCESS_MODE=qindex_only`
- `GRADE_IMAGE_INPUT_VARIANT=url`

**快路径策略（核心差异化）**：

1. 在 `qindex_only/off` 下，**先执行一次 `ocr_fallback`**（可缓存、可复用）。
2. 若无 figure/question slices 且已有 OCR：**跳过 Planner/Reflector 循环**，直接进入 Aggregator（`max_iterations=0`）。
3. Aggregator 在快路径下改为**文本聚合（Ark 推理模型 Responses API）**，避免 deep-vision 在快路径里“长时间思考/拉图”。
4. 快路径下首轮 `max_output_tokens >= 12000`，避免 “4000 截断 → 12000 重试”额外带来的 100s+ 尾部放大。
5. `image_process` 在快路径默认不启用；仅当存在明确图形证据（figure slices）再启用（作为“复核/高风险”能力）。

## 2) 证据与指标（可复现）

### 2.1 主基线（达标）

- **N=3（快路径 + 12000 tokens，稳定输出全题）**：
  - 报告：`docs/reports/grade_perf_url_n3_fast_finalize_12000_20260102.md`
  - 原始数据：`docs/reports/grade_perf_url_n3_fast_finalize_12000_20260102.json`
  - 结果（本轮同图重复）：
    - `total_ms_p50 ≈ 69s`
    - `total_ms_p95 ≈ 114s`
    - `questions_count=17`（不再退化为 1）
    - `parse_failed=0/3`、`llm_failed=0/3`、`needs_review=0/3`
    - 每次都有 `ark_response_id`（可回查）

### 2.2 关键失败样本（为什么之前“看似变快但不可用”）

这几份报告用于说明“为什么不能简单加 output cap / 开 tools 就认为会更快更稳”：

- **仅加 `max_output_tokens=4000`（速度变快但 5/5 parse_failed）**：
  - `docs/reports/grade_perf_variants_url_n5_after_max_output_tokens_20260101.md`
  - 现象：`questions_count=1`、`autonomous_agent_parse_failed=5/5`
  - 根因：deep-thinking 模型可能把输出预算全部用于 reasoning（甚至没有产出最终 `output_text`），或 JSON 被截断导致无法解析。

- **尝试 parse_retry（4000→12000）但仍不稳（4/5 parse_failed）**：
  - `docs/reports/grade_perf_url_n5_after_parse_retry_20260102.md`
  - 根因（复合）：仍在走 vision Responses + tools 路径，存在 `image_url` 拉图 timeout、reasoning 吃满导致无最终输出等问题。

- **在 vision 路径里继续修补输出提取/工具回退仍不稳**：
  - `docs/reports/grade_perf_url_n5_after_ark_output_fix_20260102.md`
  - `docs/reports/grade_perf_url_n5_after_tools_fallback_20260102.md`
  - 结论：只在 vision/tool 路径里“补丁式兜底”，很难解决 deep-thinking 的结构性不稳定（reasoning-only / incomplete）。

## 3) 根因分析（从“慢”到“稳+快”的关键转折）

### 3.1 “慢”的本质：不是 URL vs base64，而是 LLM 段 + 深度视觉链路

早期 N=10（qindex_only，多变体）基线显示：

- `docs/reports/grade_perf_variants_qindex_only_n10_img0699_20260101.md`
  - `total_ms_p50 ≈ 296s`，`total_ms_p95 ≈ 498s`
  - `llm_failed`、`queue_wait` 尾部污染、以及部分运行出现 `parse_failed`

结论：当链路走向“深度视觉推理 + 工具调用 + 输出很长的结构化 JSON”时，主要瓶颈集中在 LLM 聚合阶段，且稳定性受 deep-thinking 行为影响。

### 3.2 “稳+快”的关键：把 deep-vision 从快路径移走（转为 OCR→文本聚合）

快路径场景下（无 figure/question slices）：

- 我们不需要图像工具（image_process）或 vision 模型“反复看图”才能给出可用的全题结构；
- 先用 OCR 拿到题干/作答，再用推理模型做结构化输出，能显著降低波动与失败率；
- 这也更符合产品“证据不足要标注、不确定要可解释”的原则（OCR 不足时自然进入 `needs_review/uncertain`）。

## 4) 代码落地说明（工程师核对用）

### 4.1 关键改动点（文件级）

- 快路径 + OCR 预取 + 跳过 loop：
  - `homework_agent/services/autonomous_agent.py`
    - `qindex_only/off` 下先执行 `ocr_fallback`（并写入 `tool_ocr_fallback_ms`）
    - 满足快路径条件时 `max_iterations=0`（不进入 Planner/Reflector）
    - Aggregator 在快路径下用 text-only（`image_count=0`，`ark_image_process_requested=false`）
    - 快路径首轮 tokens 下限：`>=12000`
    - 快路径 token_budget 下限：提升到 `>=40000`（避免早退触发 `needs_review`）

- Ark Responses API（文本/多模态）调用策略与可审计输出：
  - `homework_agent/services/llm.py`
    - Ark 文本 `generate()` 改为 Responses API（便于统一审计/获取 `response_id`）
    - `LLMResult.usage` 放宽为 `Dict[str, Any]`，并统一映射 `prompt_tokens/completion_tokens/total_tokens`
    - 新增 `ARK_RESPONSES_ENABLE_OUTPUT_CAP`（默认关闭），避免 deep-thinking “reasoning 吃满 cap → 无最终输出”的不稳定

- Aggregator 输出控制（降低 token 压力，提升成功率）：
  - `homework_agent/core/prompts_autonomous.py`
    - 收紧 Aggregator 的输出契约（压缩字段、限制长度、正确题输出极简）

### 4.2 关键日志/可观测字段（核对用）

在 `logs/grade_worker.log` 中可看到（示例）：

- `agent_aggregate_start`：`image_source=ocr_only`、`image_count=0`、`ark_image_process_requested=false`
- `agent_aggregate_done`：包含 `response_id`
- `grade_ark_response_id`：API 层记录（便于 DB/日志统一查）
- `qbank_saved`：`questions_count`、`timings_ms`、`vision_raw_len`

## 5) 复现实验（给其他工程师的操作手册）

### 5.1 启动服务与 workers

（仓库根目录）

1. 启动 API：`nohup .venv/bin/uvicorn homework_agent.main:app --host 127.0.0.1 --port 8000 > logs/backend.stdout.log 2>&1 &`
2. 启动 workers：
   - `nohup .venv/bin/python -m homework_agent.workers.qindex_worker > logs/qindex_worker.stdout.log 2>&1 &`
   - `nohup .venv/bin/python -m homework_agent.workers.grade_worker > logs/grade_worker.stdout.log 2>&1 &`
   - `nohup .venv/bin/python -m homework_agent.workers.facts_worker > logs/facts_worker.stdout.log 2>&1 &`
   - `nohup .venv/bin/python -m homework_agent.workers.report_worker > logs/report_worker.stdout.log 2>&1 &`

### 5.2 跑 bench（建议先 N=3 / N=5）

```bash
.venv/bin/python scripts/bench_grade_variants_async.py \
  --api-base http://127.0.0.1:8000/api/v1 \
  --image-file "/Users/frank/Desktop/作业档案/数学/202511/1103/IMG_0699 copy.JPG" \
  --subject math \
  --vision-provider doubao \
  --llm-provider ark \
  --variants url \
  --repeat 5 \
  --user-id demo_bench_repro \
  --out-prefix grade_perf_repro_url_n5
```

输出会落到：`docs/reports/grade_perf_repro_url_n5.md/.json`

### 5.3 回查 Ark response（审计/复核）

从 bench JSON 的 `cases[*].qbank_meta.ark_response_id` 取值后：

```python
from openai import OpenAI

client = OpenAI(api_key=ARK_API_KEY, base_url=ARK_BASE_URL)
resp = client.responses.retrieve(response_id)
print(resp.to_dict().get("status"))
print(resp.to_dict().get("usage"))
```

核对点：

- `status=completed`（快路径现在能稳定完成）
- `usage.total_tokens`、`output_tokens` 与日志/bench 中 `llm_aggregate_call_ms` 对应

## 6) 风险与后续计划（下一阶段要做什么）

### 6.1 已确认的风险边界

- 快路径的“文本聚合”对图形题（几何/函数图像/复杂示意图）可能不够，需要靠 figure slices + 复核路径补强；
- 当前我们把 `image_process` 从快路径移走是为了稳定性；后续应在“有 figure slices 且 visual_risk=true”时再按需启用。

### 6.2 下一步（建议顺序）

1. 按唯一执行计划把基线从 N=3 扩到 **N=5**（日常迭代口径），并补一轮 N=5 做验收口径（≈N=10）。
2. 去掉快路径里不必要的 `compress/upload`（text-only 时无需压缩上传图片），进一步降低尾部波动。
3. 修复 proxy 闭环后再做最小验证（只验证“proxy_url 真的被使用 + 失败率/稳定性”）。

