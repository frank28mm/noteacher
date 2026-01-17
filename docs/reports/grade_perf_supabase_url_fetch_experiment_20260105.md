# /grade：Supabase URL 拉图是否影响耗时（实验）

## 结论（先读这个）
- **确实会影响**：在我们两张代表性图片的 N=5 实验里，`url`（Ark 远程抓图）相比 `data_url_first_page`（直接把图片随请求发给 Ark）在 **p95** 上更不稳定；在几何题样本里 **p50 也明显更慢**。
- **但不是“主瓶颈”**：两组实验里，`compress_download`（后端从 Supabase 下载图片用于压缩/上传）只有 **~5–7s/次**，而 **LLM 主调用 ~110–135s/次**；所以“换存储/走内网”最多是“修尾延迟/抖动”，不太可能把总耗时从 2–3 分钟降到 10–20 秒。
- **迁移到火山（TOS/同地域）仍然值得**：因为 `data_url` 更像“没有远程抓图抖动”的理想上限；把图片放到 **华东 TOS + 内网/同地域访问**，理论上能把 `url` 的表现拉近 `data_url`，尤其是 p95。

## 实验设计
- 目的：验证“Supabase URL 远程抓图”对 `/grade` 耗时的贡献（尤其是尾延迟）。
- 方法：同一张图，跑两种输入策略（N=5）：
  - `url`：Ark 看到的是图片 URL（会去远程抓图）。
  - `data_url_first_page`：把图片以 data URL 形式直接随请求发送（不需要 Ark 再抓图）。
- 固定条件：
  - `AUTONOMOUS_PREPROCESS_MODE=qindex_only`
  - `ARK_IMAGE_PROCESS_ENABLED=0`（避免视觉工具干扰）
  - 单 `grade_worker`，无排队干扰（queue_wait p50≈10ms 量级）

## 数据（p50/p95）
> `total_s` 为用户感知的 `/grade` 总耗时；`download_s` 为后端 `compress_download_ms`；`llm_call_s` 为 LLM 聚合调用耗时（`llm_aggregate_call_ms`）。

### 样本 1：IMG_0699（数学作业照片）
- `url`：`total_s p50=153.3 / p95=219.2`；`download_s p50=5.52`；`llm_call_s p50=125.5`
- `data_url_first_page`：`total_s p50=153.4 / p95=181.6`；`download_s p50=6.13`；`llm_call_s p50=129.4`
- 解读：p50 基本一致，但 **p95 明显更稳**（约 -37s）。该样本里“远程抓图”更像是 **尾延迟抖动来源**，不是稳定性/中位数瓶颈。

### 样本 2：IMG_1100（几何/图形类题目）
- `url`：`total_s p50=152.4 / p95=175.3`；`download_s p50=4.64`；`llm_call_s p50=134.5`
- `data_url_first_page`：`total_s p50=135.6 / p95=165.6`；`download_s p50=5.00`；`llm_call_s p50=111.3`
- 解读：**p50 直接变快（约 -16.8s）**，且 LLM 调用本身也更快（约 -23s）。这更符合“URL 抓图会让模型端/链路端更慢”的直觉。

## 这对“迁移到火山存储/内网”的含义
- 当前我们能量化的“可优化空间”大致是：
  - **中位数**：0–20s/次（样本依赖明显）
  - **尾延迟**：10–40s/次（更稳定）
- 迁移图片存储到 **火山华东 TOS**（并尽量让 Ark 到 TOS 走同地域/内网）后，`url` 变体的表现应该更接近 `data_url`，但 **LLM 计算本身仍是主耗时**（100s+）。

## 产物（原始数据）
- `docs/reports/grade_perf_url_vs_data_url_first_page_n5_img0699_20260105.md`
- `docs/reports/grade_perf_url_vs_data_url_first_page_n5_img0699_20260105.json`
- `docs/reports/grade_perf_url_vs_data_url_first_page_n5_img1100_20260105.md`
- `docs/reports/grade_perf_url_vs_data_url_first_page_n5_img1100_20260105.json`

