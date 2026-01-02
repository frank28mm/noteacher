# /grade 输入策略对比（async）

- generated_at: `20260101_212344`
- preprocess_mode(label): `qindex_only`
- upload_id: `upl_ba8efe1891ff42eb`
- upload_ms: `31122`
- repeat: `10`
- completed_cases: `30`

## 汇总（p50/p95）
| variant | n | total_ms_p50 | total_ms_p95 | queue_wait_p50 | queue_wait_p95 | grade_total_p50 | grade_total_p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| url | 10 | 312079 | 498335 | 5 | 144864 | 273150 | 371621 |
| proxy | 10 | 224866 | 383639 | 10 | 191492 | 192058 | 382009 |
| data_url_first_page | 10 | 352779 | 688901 | 9 | 327540 | 350966 | 406785 |

## 明细（每次运行）
| variant | status | queue_wait_ms | total_ms | preprocess_total_ms | llm_aggregate_call_ms | grade_total_duration_ms | ark_image_process_requested | ark_image_process_enabled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| url | done | 38510 | 312079 | 0 | 235772 | 273150 | true | true |
| url | done | 5 | 241122 | 0 | 196397 | 239510 | true | true |
| url | done | 5 | 317180 | 0 | 206640 | 316053 | true | true |
| url | done | 6 | 177109 | 0 | 134515 | 175497 | true | true |
| url | done | 5 | 316126 | 0 | 268100 | 315244 | true | true |
| url | done | 5 | 227953 | 0 | 180092 | 225918 | true | true |
| url | done | 6 | 372752 | 0 | 217294 | 371621 | true | true |
| url | done | 5 | 267652 | 0 | 237432 | 265023 | true | true |
| url | done | 144864 | 498335 | 0 | 295183 | 351852 | true | true |
| url | done | 5 | 359100 | 0 | 193454 | 356185 | true | true |
| proxy | done | 10 | 167927 | 0 |  | 166614 | false | false |
| proxy | done | 10 | 325685 | 0 | 293996 | 324265 | true | true |
| proxy | done | 10 | 50882 | 0 |  | 50104 | false | false |
| proxy | done | 10 | 114281 | 0 |  | 112638 | false | false |
| proxy | done | 10 | 383639 | 0 | 237695 | 382009 | true | true |
| proxy | done | 5 | 259855 | 0 | 197107 | 259174 | true | true |
| proxy | done | 5 | 194542 | 0 | 158063 | 192058 | true | true |
| proxy | done | 191492 | 323285 | 0 |  | 130992 | false | false |
| proxy | done | 7 | 224866 | 0 | 194434 | 223637 | true | true |
| proxy | done | 5 | 292383 | 0 | 252066 | 291015 | true | true |
| data_url_first_page | done | 10 | 282156 | 0 | 216970 | 279900 | true | true |
| data_url_first_page | done | 10 | 387059 | 0 | 254970 | 384417 | true | true |
| data_url_first_page | done | 8 | 379936 | 0 | 216417 | 375724 | true | true |
| data_url_first_page | done | 4 | 408572 | 0 | 258201 | 406785 | true | true |
| data_url_first_page | done | 327540 | 688901 | 0 | 242852 | 359760 | true | true |
| data_url_first_page | done | 9 | 364350 | 0 | 210395 | 360682 | true | true |
| data_url_first_page | done | 7 | 273365 | 0 | 215705 | 269789 | true | true |
| data_url_first_page | done | 8 | 219780 | 0 | 178705 | 216260 | true | true |
| data_url_first_page | done | 9 | 296017 | 0 | 252110 | 293737 | true | true |
| data_url_first_page | done | 9 | 352779 | 0 | 177811 | 350966 | true | true |

- raw_json: `docs/reports/grade_perf_variants_qindex_only_n10_img0699_20260101.json`
