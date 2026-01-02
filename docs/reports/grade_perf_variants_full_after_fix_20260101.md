# /grade 输入策略对比（async）

- generated_at: `20260101_145518`
- preprocess_mode(label): `full`
- upload_id: `upl_59e20725b4154c15`
- upload_ms: `7775`

| variant | status | queue_wait_ms | total_ms | preprocess_total_ms | llm_aggregate_call_ms | grade_total_duration_ms | ark_image_process_requested | ark_image_process_enabled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| url | done | 5 | 489084 | 227620 | 199018 | 488163 | true | true |
| proxy | done | 5 | 766652 | 81212 |  | 600002 | false | false |
| data_url_first_page | done | 5 | 507924 | 99230 | 236828 | 506519 | true | true |

- raw_json: `docs/reports/grade_perf_variants_full_after_fix_20260101.json`
