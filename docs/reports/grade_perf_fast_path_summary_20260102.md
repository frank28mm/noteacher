# /grade 快路径性能与质量复盘（URL-only，qindex_only）

本报告汇总 2026-01-02 对 `/api/v1/grade` 的性能与稳定性优化结论，并给出当前推荐的“快路径”策略与后续工作项。

## 1) 结论（当前推荐默认）

- **默认策略**：`AUTONOMOUS_PREPROCESS_MODE=qindex_only` + `GRADE_IMAGE_INPUT_VARIANT=url`
- **快路径原则**：先拿到 OCR（可缓存）→ 直接走 **文本聚合**（Ark 推理模型），避免 deep-vision 在快路径里长时间“思考/拉图”。
- **image_process**：在快路径中默认不启用；仅当存在明确图形证据（figure slices）时再启用（作为“复核/高风险”能力）。

## 2) 关键实现变更（代码级）

- `/grade` 在 `qindex_only/off` 下：**先执行一次 `ocr_fallback`**（命中缓存后为秒级），保证 `ocr_text` 可用。
- 满足快路径条件时：**跳过 Planner/Reflector 循环**（`max_iterations=0`），直接进入 Aggregator。
- Aggregator 在快路径下：改用 **Ark 推理模型的 Responses API（文本模式）**，并将 `max_output_tokens` 提升到 `>=12000`，避免“先 4000 截断 → 再 12000 重试”带来的 100s+ 额外耗时。

## 3) 最新基线（可复现证据）

- N=3（快路径 + 12000 tokens，达标）：`docs/reports/grade_perf_url_n3_fast_finalize_12000_20260102.md`
  - 结果：`p50 ≈ 69s`，`p95 ≈ 114s`，`questions_count=17`，`parse_retry=0`
- 早期问题样本（供追溯）：
  - 仅 4000 tokens（触发 parse_retry，导致 160s+）：`docs/reports/grade_perf_url_n3_fast_finalize_20260102.md`
  - vision Responses 强行 output cap（reasoning 吃满导致无 output_text）：`docs/reports/grade_perf_url_n5_after_ark_output_fix_20260102.md`

## 4) 仍需完成的后续（建议按优先级）

- 将“快路径不压缩/不上传图片”再前移（text-only 时无需做 compress/upload），进一步压缩尾部耗时。
- 将 N=3 升级到 **N=5**（日常迭代口径），并定期补一轮 N=5（≈N=10）用于决策/验收。
- Proxy 变体闭环修复后，再做最小验证（只验证 “proxy_url 是否真的被使用 + 失败率”），不扩散对比范围。

