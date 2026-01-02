# /grade 输入策略对比（async）

- generated_at: `20260102_114522`
- preprocess_mode(label): `full`
- upload_id: `upl_11953b14b3984aee`
- upload_ms: `6647`
- repeat: `5`
- completed_cases: `5`

## 汇总（p50/p95）
| variant | n | total_ms_p50 | total_ms_p95 | queue_wait_p50 | queue_wait_p95 | grade_total_p50 | grade_total_p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| url | 5 | 271811 | 316604 | 8 | 14 | 271185 | 315233 |

## 明细（每次运行）
| variant | status | queue_wait_ms | total_ms | preprocess_total_ms | llm_aggregate_call_ms | grade_total_duration_ms | ark_image_process_requested | ark_image_process_enabled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| url | done | 8 | 276914 | 101371 | 127012 | 275702 | false | true |
| url | done | 8 | 316604 | 84409 | 192178 | 315233 | false | true |
| url | done | 14 | 252465 | 69328 | 140927 | 251561 | false | true |
| url | done | 9 | 266598 | 84308 | 141739 | 265231 | false | true |
| url | done | 8 | 271811 | 90830 | 124736 | 271185 | false | true |

- raw_json: `docs/reports/grade_perf_visual_img0699_full_url_n5_20260102.json`
