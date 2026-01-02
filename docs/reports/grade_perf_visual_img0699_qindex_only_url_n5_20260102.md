# /grade 输入策略对比（async）

- generated_at: `20260102_112926`
- preprocess_mode(label): `qindex_only`
- upload_id: `upl_7d6d821628534b11`
- upload_ms: `6003`
- repeat: `5`
- completed_cases: `5`

## 汇总（p50/p95）
| variant | n | total_ms_p50 | total_ms_p95 | queue_wait_p50 | queue_wait_p95 | grade_total_p50 | grade_total_p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| url | 5 | 99667 | 124013 | 9 | 11 | 95700 | 122466 |

## 明细（每次运行）
| variant | status | queue_wait_ms | total_ms | preprocess_total_ms | llm_aggregate_call_ms | grade_total_duration_ms | ark_image_process_requested | ark_image_process_enabled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| url | done | 11 | 99667 | 2 | 89288 | 95700 | false | true |
| url | done | 10 | 124013 | 0 | 118217 | 122466 | false | true |
| url | done | 9 | 113734 | 0 | 108663 | 112260 | false | true |
| url | done | 8 | 84283 | 0 | 78781 | 83616 | false | true |
| url | done | 7 | 95499 | 0 | 89899 | 94073 | false | true |

- raw_json: `docs/reports/grade_perf_visual_img0699_qindex_only_url_n5_20260102.json`
