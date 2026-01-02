# /grade 输入策略对比（async）

- generated_at: `20260102_120852`
- preprocess_mode(label): `full`
- upload_id: `upl_7bf3c631acf34b92`
- upload_ms: `4825`
- repeat: `5`
- completed_cases: `5`

## 汇总（p50/p95）
| variant | n | total_ms_p50 | total_ms_p95 | queue_wait_p50 | queue_wait_p95 | grade_total_p50 | grade_total_p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| url | 5 | 225940 | 263524 | 10 | 25 | 224908 | 261334 |

## 明细（每次运行）
| variant | status | queue_wait_ms | total_ms | preprocess_total_ms | llm_aggregate_call_ms | grade_total_duration_ms | ark_image_process_requested | ark_image_process_enabled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| url | done | 10 | 263524 | 89556 | 76576 | 261334 | true | true |
| url | done | 8 | 225940 | 69890 | 87640 | 224908 | true | true |
| url | done | 25 | 199446 | 101557 |  | 198016 | false | false |
| url | done | 10 | 209591 | 119922 | 27042 | 208740 | true | true |
| url | done | 9 | 248340 | 94598 | 75092 | 246911 | true | true |

- raw_json: `docs/reports/grade_perf_visual_img1100_full_url_n5_20260102.json`
