# /grade 性能根因定位：实验结论（2026-01-01）

本报告基于一次真实 Demo 测试与两轮可复现实验（多变体、多配置）产出，目标是回答：
1) **慢到底慢在哪**；2) **哪些开关/策略最有效**；3) **下一步先改哪里最值**。

## 1. 本次确认的关键结论（结论先行）

### 1) `/grade` 的慢主要来自两类因素
- **队列排队（非计算）**：当 Redis 队列里存在遗留 job 或 worker 串行处理多个任务时，`/jobs` 会在 `processing` 状态停很久。
- **“前置预处理”耗时（计算但可避免）**：默认 `full` 模式会做 VLM 定位 + 批量切片上传，单页也可达 **80–220s**，且本次并未被 aggregator 使用（浪费）。

### 2) 发现并修复了一个会导致异步 job “偶发失败”的 P0 Bug
- 触发条件：质量闸门 `gate_warnings` 不为空时。
- 现象：grade_worker 中 job 直接失败，错误为 `NameError: name 'response' is not defined`。
- 根因：`homework_agent/api/grade.py` 的 `_perform_autonomous_grading()` 在 worker 场景错误引用了 FastAPI 的 `response` 变量（该作用域不存在）。
- 修复：仅把 gate_warnings 合并到 `grading_result.warnings`，不再触碰 `response`。

### 3) 一键收益最大的开关：`AUTONOMOUS_PREPROCESS_MODE=off`
- `full → off` 在同一张作业图上，端到端（grade_total_duration）从 **~500–760s** 降到 **~190–250s**（数量级提升）。
- 结论：**预处理必须从 grade 快路径移出**，改为 strict/repair path（视觉风险/复核时再触发）。

## 2. 实验与数据（可复现）

### 2.1 单次 Demo 跑通（作为基线样本）
报告：`docs/reports/demo_ui2_run_20260101_133600.md`

关键观察：
- enqueued `13:22:49` → grade_worker start `13:29:18`（排队 ~389s）
- worker 计算 `~328s`，其中：
  - preprocess_total `~96s`
  - llm_aggregate_call `~194s`
- `ark_image_process_enabled=true` 且 `ark_image_process_requested=true`

### 2.2 多变体对比（`AUTONOMOUS_PREPROCESS_MODE=full`）
报告：
- `docs/reports/grade_perf_variants_full_after_fix_20260101.md`
- `docs/reports/grade_perf_variants_full_after_fix_20260101.json`

结论要点：
- `preprocess_total_ms` 波动极大（81s~227s），是最大不稳定项。
- 某些 case 会进入 600s 超时并报 `autonomous_agent_llm_failed`（需要单独做重试/降级与输入控制）。

### 2.3 多变体对比（`AUTONOMOUS_PREPROCESS_MODE=off`）
报告：
- `docs/reports/grade_perf_variants_off_variantprop_20260101.md`
- `docs/reports/grade_perf_variants_off_variantprop_20260101.json`

结论要点：
- `preprocess_total_ms=0` 后，整体明显变快、且稳定性更好（未再出现 200s+ 的 preprocess）。
- `data_url_first_page` 能真正生效（`agent_aggregate_start.image_input_mode=data_url`），并记录 `image_data_url_download_encode_ms`（本次约 3.2s）。
- `url` vs `data_url_first_page` 的差距在本样本下不夸张，但 `data_url` 能规避 Ark 远程抓图的不确定性，值得保留为可控策略。

## 3. 你要的“慢原因”拆解（可操作）

### A) 为什么会“排队很久”
- 触发：Redis 队列里有历史任务、或只有 1 个 grade_worker。
- 解决：
  - 测试时：清空 `grade:queue` 或使用不同 `CACHE_PREFIX` 隔离实验。
  - 生产时：grade_worker 横向扩容 + 限流 + 按 user_id 做公平调度（后续 P1）。

### B) 为什么预处理这么慢、还可能白做
默认 `full` 会做：
- VLM bbox 定位（SiliconFlow locator）
- 为 10+ 题批量裁剪并上传切片（I/O 大）

但 aggregator 只在 `figure_urls` 可用且 figure 不小的时候才优先用 slices；否则仍走原图压缩后输入。
因此容易出现：**花 1~2 分钟做切片，最后还是用原图**。

## 4. 下一步建议（按价值排序）

P0（立刻做，直接提升体验）
1) 把 `AUTONOMOUS_PREPROCESS_MODE` 默认改为 `off`（或 `qindex_only`），并把“切片/VLM 定位”移动到 strict/repair path。
2) 把 `proxy` 变体做成“真实 proxy”而不是仅仅 prefer_proxy（需要在 /grade 里生成并落 `proxy_page_image_urls`）。
3) 把 `data_url_first_page` 做成可控实验开关（已可用），并用同一套脚本跑 10 次取 p50/p95。

P1（稳定性/成本）
1) 让 `/jobs` 状态里补充 `started_at/enqueued_at`（目前只能靠日志推断 queue_wait）。
2) 把 `grade_image_input_variant`、`ark_response_id`、`ark_image_process_*` 统一落库到 `submissions.grade_result._meta`（现在已有部分）。

