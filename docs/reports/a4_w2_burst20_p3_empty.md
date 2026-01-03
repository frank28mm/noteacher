# A-4 生产等价压测（Load / Async）

- generated_at: `a4_w2_burst20_p3_empty`
- api_base: `http://localhost:8000/api/v1`
- user_id: `demo_perf_20260101_qindex_only_01`
- worker_count(label): `2`
- burst_submissions: `20`
- pages_per_submission: `3`
- subject: `math`
- vision_provider: `doubao`
- llm_provider: `ark`
- upload_concurrency: `4`
- grade_concurrency: `20`
- poll_interval_seconds: `2.0`
- timeout_seconds: `3600`

## 汇总
- n_total: `20`
- n_ok: `14`
- n_failed: `6`

| metric | p50_ms | p95_ms | max_ms |
|---|---:|---:|---:|
| queue_wait_ms | 1454298 | 2961240 | 3032468 |
| ttv_first_page_ms | 1652778 | 3141768 | 3168884 |
| worker_elapsed_ms | 521314 | 585473 | 680743 |
| ttd_done_ms | 2031612 | 3495434 | 3504229 |

## 明细（每次 submission）
| idx | pages | status | upload_ms | submit_ms | queue_wait_ms | ttv_first_page_ms | worker_elapsed_ms | ttd_done_ms |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 0 | 3 | done | 64687 | 5591 | 533122 | 699644 | 503139 | 1036261 |
| 1 | 3 | done | 39769 | 24918 | 0 | 205163 | 538418 | 538418 |
| 2 | 3 | done | 62674 | 5810 | 532909 | 805833 | 585473 | 1118382 |
| 3 | 3 | done | 56041 | 12425 | 0 | 180137 | 534227 | 534227 |
| 4 | 3 | done | 81509 | 14352 | 1454298 | 1652778 | 680743 | 2135041 |
| 5 | 3 | done | 65236 | 14352 | 1051815 | 1220233 | 540365 | 1592180 |
| 6 | 3 | done | 76591 | 1987 | 1585701 | 1732202 | 445911 | 2031612 |
| 7 | 3 | done | 42961 | 19775 | 979795 | 1132199 | 483440 | 1463235 |
| 8 | 3 | done | 60067 | 11856 | 1994948 | 2145612 | 537744 | 2532692 |
| 9 | 3 | done | 49886 | 15554 | 2085108 | 2263564 | 521314 | 2606422 |
| 10 | 3 | done | 65442 | 1734 | 2522049 | 2682543 | 472712 | 2994761 |
| 11 | 3 | done | 59234 | 1947 | 2592335 | 2754954 | 471906 | 3064241 |
| 12 | 3 | done | 55329 | 9074 | 3032468 | 3168884 | 462966 | 3495434 |
| 13 | 3 | done | 45006 | 6871 | 2961240 | 3141768 | 542989 | 3504229 |
| 14 | 3 | failed | 0 | 0 | 0 |  |  |  |
| 15 | 3 | failed | 0 | 0 | 0 |  |  |  |
| 16 | 3 | failed | 0 | 0 | 0 |  |  |  |
| 17 | 3 | failed | 0 | 0 | 0 |  |  |  |
| 18 | 3 | failed | 0 | 0 | 0 |  |  |  |
| 19 | 3 | failed | 0 | 0 | 0 |  |  |  |

## 逐页可用（可解释证据）
每条记录会输出 `per_page_ready_ms`（page_index→ms），用于确认“第 1 页可用是否足够早”。
