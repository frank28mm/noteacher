# A‑4 worker 并发敏感性复测（worker=1 vs worker=4，burst=10，3页/次）

本报告用于补齐 `WS‑A / A‑4.2`：“worker 并发敏感性（worker=1 vs worker=4）”，为后续 `WS‑D（VKE/K8s 扩缩容阈值）`提供直接证据。

## 1) 证据文件（原始明细）

- `docs/reports/a4_w1_burst10_p3_empty_20260105.md`（worker=1，空队列起步，burst=10，3页/次）
- `docs/reports/a4_w4_burst10_p3_empty_20260105.md`（worker=4，空队列起步，burst=10，3页/次）

## 2) 测试设置（两轮一致）

- burst：`10 submissions`（同一时刻入队）
- pages：`3 pages / submission`
- `upload_concurrency=2`（避免 Supabase Storage 并发上传不稳定干扰）
- `grade_concurrency=10`（尽量形成真实 burst）
- `poll_interval_seconds=2`
- 重要：`worker_count(label)` 仅用于记录；实际并发由启动的 `grade_worker` 进程数决定（每个进程单任务串行消费）。

## 3) 结论（最关键的变化）

### 3.1 worker_elapsed 基本不随 worker 数变化（内部速度稳定）

两轮的 `worker_elapsed_ms`（3页）接近：

- worker=1：p50 `433s`，p95 `672s`
- worker=4：p50 `423s`，p95 `638s`

含义：**单个作业开始跑以后，内部耗时由 LLM/处理链路决定，扩 worker 不会让单个作业“更快”，只会让“更早开始跑”。**

### 3.2 queue_wait 显著随 worker 数下降（排队敏感性强）

同样的 burst=10：

- worker=1：`queue_wait_ms` p50 `1953s`（≈32.5min），p95 `3994s`（≈66.6min）
- worker=4：`queue_wait_ms` p50 `457s`（≈7.6min），p95 `837s`（≈13.9min）

含义：**系统体验的瓶颈主要来自“是否有足够并发 worker 承接峰值”，而不是快路径本身。**

### 3.3 第 1 页可用（TTV）主要由 queue_wait 决定

`ttv_first_page_ms`（从入队开始到第 1 页可用）：

- worker=1：p50 `2101s`（≈35.0min），p95 `4138s`（≈69.0min）
- worker=4：p50 `574s`（≈9.6min），p95 `935s`（≈15.6min）

> 备注：可近似理解为 `TTV ≈ queue_wait + 常数(≈2–3min)`，其中常数来自“job 开始跑后第 1 页可用”的内部链路。

## 4) 扩容含义（把数据翻译成决策）

### 4.1 “最低并发”直觉（burst=10, 3页/次）

- **worker=1**：TTV p50≈35min，明显不可接受（用户长时间看不到任何结果）。
- **worker=4**：TTV p50≈10min，仍会让用户明显等待，但“不会无限排队”，可作为“低配起步并发”的下限。
- 若希望 burst=10 时“几乎不排队”（p95(queue_wait) 接近 0）：**需要 worker ≈ burst（即 ≥10）**，因为每个 job 都要 7–11 分钟的 worker 时间，worker=4 只会必然形成积压。

### 4.2 对 `WS‑D（KEDA/VCI）` 的直接启示

- `grade_worker` 单 Pod 并发=1 的前提下，扩容的核心就是“**按队列积压扩 Pod 数**”。
- 经验阈值（基于本次样本，给出“工程可用”的起点）：
  - **minReplicas**：平峰可为 0–1（你已偏好平峰≈0）
  - **maxReplicas**：至少覆盖 `burst` 的量级（例如 burst=10 → max≥10；burst=20 → max≥20），否则必然产生长排队
  - **KEDA listLength**：建议从 `1` 起步（队列每积压 1 个 job 就扩 1 个 Pod），再结合实际冷启动延迟调节

## 5) 本轮完成度（对齐 WS‑A）

- ✅ 已补齐 `A‑4.2 worker=1 vs worker=4` 的证据与结论（用于扩缩容阈值）。
- ⚠️ 仍建议后续补一轮“生产对象存储（Ark/TOS）环境”复测：本轮为了可控，限制了并发上传；切换存储后可把 upload_concurrency 拉高再观测。

