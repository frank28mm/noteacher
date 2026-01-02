# /grade 输入策略对比（async）

- generated_at: `20260102_113828`
- preprocess_mode(label): `qindex_only`
- upload_id: `upl_522f21c20bb14ee9`
- upload_ms: `5931`
- repeat: `5`
- completed_cases: `5`

## 汇总（p50/p95）
| variant | n | total_ms_p50 | total_ms_p95 | queue_wait_p50 | queue_wait_p95 | grade_total_p50 | grade_total_p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| url | 5 | 71208 | 80414 | 9 | 9 | 70135 | 79170 |

## 明细（每次运行）
| variant | status | queue_wait_ms | total_ms | preprocess_total_ms | llm_aggregate_call_ms | grade_total_duration_ms | ark_image_process_requested | ark_image_process_enabled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| url | done | 9 | 71208 | 0 | 37227 | 70135 | false | true |
| url | done | 8 | 74261 | 0 | 68407 | 72585 | false | true |
| url | done | 9 | 68193 | 0 | 62628 | 66818 | false | true |
| url | done | 8 | 80414 | 0 | 74764 | 79170 | false | true |
| url | done | 9 | 64146 | 0 | 59355 | 63345 | false | true |

- raw_json: `docs/reports/grade_perf_visual_img1100_qindex_only_url_n5_20260102.json`
