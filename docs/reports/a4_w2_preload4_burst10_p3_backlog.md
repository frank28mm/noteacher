# A-4 生产等价压测（Load / Async）

- generated_at: `a4_w2_preload4_burst10_p3_backlog`
- api_base: `http://localhost:8000/api/v1`
- user_id: `demo_perf_20260101_qindex_only_01`
- worker_count(label): `2`
- burst_submissions: `10`
- pages_per_submission: `3`
- subject: `math`
- vision_provider: `doubao`
- llm_provider: `ark`
- preload_submissions: `4`
- preload_hold_seconds: `10.0`
- upload_concurrency: `4`
- grade_concurrency: `10`
- poll_interval_seconds: `2.0`
- timeout_seconds: `3600`

## 汇总
- n_total: `10`
- n_ok: `4`
- n_failed: `6`

| metric | p50_ms | p95_ms | max_ms |
|---|---:|---:|---:|
| queue_wait_ms | 2736730 | 2753842 | 2753842 |
| ttv_first_page_ms | 2892641 | 2901593 | 2901593 |
| worker_elapsed_ms | 474595 | 525374 | 525374 |
| ttd_done_ms | 3193382 | 3228437 | 3228437 |

## 明细（每次 submission）
| idx | pages | status | upload_ms | submit_ms | queue_wait_ms | ttv_first_page_ms | worker_elapsed_ms | ttd_done_ms |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 0 | 3 | failed | 0 | 0 | 0 |  |  |  |
| 1 | 3 | done | 42814 | 6293 | 2213556 | 2382613 | 525374 | 2738930 |
| 2 | 3 | done | 45734 | 5022 | 2736730 | 2901593 | 456652 | 3193382 |
| 3 | 3 | done | 42814 | 6292 | 2310257 | 2481135 | 473019 | 2783276 |
| 4 | 3 | done | 39277 | 13039 | 2753842 | 2892641 | 474595 | 3228437 |
| 5 | 3 | failed | 0 | 0 | 0 |  |  |  |
| 6 | 3 | failed | 0 | 0 | 0 |  |  |  |
| 7 | 3 | failed | 0 | 0 | 0 |  |  |  |
| 8 | 3 | failed | 0 | 0 | 0 |  |  |  |
| 9 | 3 | failed | 0 | 0 | 0 |  |  |  |

## 逐页可用（可解释证据）
每条记录会输出 `per_page_ready_ms`（page_index→ms），用于确认“第 1 页可用是否足够早”。
