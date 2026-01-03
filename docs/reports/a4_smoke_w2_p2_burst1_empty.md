# A-4 生产等价压测（Load / Async）

- generated_at: `a4_smoke_w2_p2_burst1_empty`
- api_base: `http://localhost:8000/api/v1`
- user_id: `demo_perf_20260101_qindex_only_01`
- worker_count(label): `2`
- burst_submissions: `1`
- pages_per_submission: `2`
- subject: `math`
- vision_provider: `doubao`
- llm_provider: `ark`
- upload_concurrency: `1`
- grade_concurrency: `1`
- poll_interval_seconds: `2.0`
- timeout_seconds: `1800`

## 汇总
- n_total: `1`
- n_ok: `1`
- n_failed: `0`

| metric | p50_ms | p95_ms | max_ms |
|---|---:|---:|---:|
| queue_wait_ms |  |  |  |
| ttv_first_page_ms | 156337 | 156337 | 156337 |
| worker_elapsed_ms | 395801 | 395801 | 395801 |
| ttd_done_ms | 395801 | 395801 | 395801 |

## 明细（每次 submission）
| idx | pages | status | upload_ms | submit_ms | queue_wait_ms | ttv_first_page_ms | worker_elapsed_ms | ttd_done_ms |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 0 | 2 | done | 8804 | 1852 | 0 | 156337 | 395801 | 395801 |

## 逐页可用（可解释证据）
每条记录会输出 `per_page_ready_ms`（page_index→ms），用于确认“第 1 页可用是否足够早”。
