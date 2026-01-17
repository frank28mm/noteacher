# /grade 输入策略对比（async）

- generated_at: `20260105_105022`
- preprocess_mode(label): `qindex_only`
- upload_id: `upl_b1c8fc4c588d402f`
- upload_ms: `20382`
- repeat: `5`
- completed_cases: `10`

## 汇总（p50/p95）
| variant | n | total_ms_p50 | total_ms_p95 | queue_wait_p50 | queue_wait_p95 | grade_total_p50 | grade_total_p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| url | 5 | 153331 | 232079 | 10 | 11 | 150085 | 229223 |
| data_url_first_page | 5 | 153365 | 183591 | 10 | 11 | 149928 | 180571 |

## 明细（每次运行）
| variant | status | queue_wait_ms | total_ms | preprocess_total_ms | llm_aggregate_call_ms | grade_total_duration_ms | ark_image_process_requested | ark_image_process_enabled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| url | done | 11 | 232079 | 1 | 125453 | 229223 | false | false |
| url | done | 11 | 121108 | 1 | 99855 | 116535 | false | false |
| url | done | 7 | 139191 | 0 | 121262 | 135067 | false | false |
| url | done | 10 | 153331 | 0 | 134223 | 150085 | false | false |
| url | done | 10 | 167474 | 0 | 151217 | 164176 | false | false |
| data_url_first_page | done | 10 | 183591 | 0 | 158214 | 180571 | false | false |
| data_url_first_page | done | 10 | 151321 | 0 | 129376 | 148549 | false | false |
| data_url_first_page | done | 10 | 153365 | 0 | 128357 | 149928 | false | false |
| data_url_first_page | done | 10 | 151364 | 0 | 124431 | 148224 | false | false |
| data_url_first_page | done | 11 | 173548 | 0 | 148404 | 170065 | false | false |

- raw_json: `docs/reports/grade_perf_url_vs_data_url_first_page_n5_img0699_20260105.json`
