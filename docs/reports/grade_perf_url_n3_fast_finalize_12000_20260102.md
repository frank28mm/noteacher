# /grade 输入策略对比（async）

- generated_at: `20260102_031317`
- preprocess_mode(label): `qindex_only`
- upload_id: `upl_8d763684431e469a`
- upload_ms: `5914`
- repeat: `3`
- completed_cases: `3`

## 汇总（p50/p95）
| variant | n | total_ms_p50 | total_ms_p95 | queue_wait_p50 | queue_wait_p95 | grade_total_p50 | grade_total_p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| url | 3 | 69822 | 114342 | 4 | 4 | 69042 | 113634 |

## 明细（每次运行）
| variant | status | queue_wait_ms | total_ms | preprocess_total_ms | llm_aggregate_call_ms | grade_total_duration_ms | ark_image_process_requested | ark_image_process_enabled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| url | done | 4 | 68760 | 0 | 61157 | 67112 | false | true |
| url | done | 4 | 69822 | 0 | 65248 | 69042 | false | true |
| url | done | 4 | 114342 | 0 | 109884 | 113634 | false | true |

- raw_json: `docs/reports/grade_perf_url_n3_fast_finalize_12000_20260102.json`
