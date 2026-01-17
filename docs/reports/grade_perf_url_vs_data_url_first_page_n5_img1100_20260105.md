# /grade 输入策略对比（async）

- generated_at: `20260105_114338`
- preprocess_mode(label): `qindex_only`
- upload_id: `upl_136c48bd311744d4`
- upload_ms: `13823`
- repeat: `5`
- completed_cases: `10`

## 汇总（p50/p95）
| variant | n | total_ms_p50 | total_ms_p95 | queue_wait_p50 | queue_wait_p95 | grade_total_p50 | grade_total_p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| url | 5 | 152384 | 178222 | 27 | 29 | 150017 | 175462 |
| data_url_first_page | 5 | 135617 | 165820 | 28 | 28 | 132696 | 163217 |

## 明细（每次运行）
| variant | status | queue_wait_ms | total_ms | preprocess_total_ms | llm_aggregate_call_ms | grade_total_duration_ms | ark_image_process_requested | ark_image_process_enabled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| url | done | 13 | 178222 | 0 | 132575 | 175462 | false | false |
| url | done | 28 | 163745 | 0 | 146142 | 160565 | false | false |
| url | done | 29 | 152384 | 1 | 135653 | 150017 | false | false |
| url | done | 18 | 152367 | 0 | 134541 | 148285 | false | false |
| url | done | 27 | 147143 | 0 | 130355 | 143782 | false | false |
| data_url_first_page | done | 28 | 165820 | 0 | 142112 | 163217 | false | false |
| data_url_first_page | done | 28 | 118162 | 0 | 95400 | 115954 | false | false |
| data_url_first_page | done | 28 | 135617 | 0 | 111271 | 132696 | false | false |
| data_url_first_page | done | 19 | 164603 | 0 | 140238 | 162114 | false | false |
| data_url_first_page | done | 27 | 118143 | 0 | 96963 | 115375 | false | false |

- raw_json: `docs/reports/grade_perf_url_vs_data_url_first_page_n5_img1100_20260105.json`
