# Demo Benchmark Report (2025-12-21)

## Scope
- 目标：验证 **全 Doubao** 与 **全 Qwen3** 两条链路的耗时/稳定性，检查 `judgment_basis` 条数限制与 Chat 表现。
- 图像：`/Users/frank/Desktop/作业档案/数学/202511/1103/IMG_0699 copy.JPG`
- 环境：本机 `127.0.0.1:8000`，后端 + demo + qindex worker 已启动。

## 运行结果

### Run A — 全 Doubao
- session_id：`bench_doubao_1766327286`
- upload_id：`upl_f4c2dedcf7a24c26`
- providers：vision=`doubao`，llm=`ark`
- upload 耗时：**8.58s**
- grade 耗时：**234.07s**
- grade status：`done`
- total_items：16
- wrong_count：8
- warnings（2 条）：
  - 视觉事实解析失败，本次判断仅基于识别原文。
  - 视觉事实解析失败，本次判断仅基于识别原文。
- judgment_basis 条数统计：min=3, max=3, avg=3.0（符合 2–5 条要求）
- Chat（问："讲讲第9题"）
  - chat_len：99
  - chat_head：`你的答案$2x^2 -2x$是正确的哦！...`

**结论**：可完成，但整体耗时长（≈4 分钟）。视觉事实解析仍失败，warning 重复。

---

### Run B — 全 Qwen3
- session_id：`bench_qwen3_1766327538`
- upload_id：`upl_0169ca18f57b4f33`
- providers：vision=`qwen3`，llm=`silicon`
- upload 耗时：**7.23s**
- grade 耗时：**243.33s**
- grade status：`failed`
- warnings：
  - Vision analysis failed: timeout after 240s
- Chat（问："讲讲第9题"）
  - chat_len：77
  - chat_head：`我还没有拿到本次作业的“题库快照”...`

**结论**：Qwen3 vision 在 240s 超时，无法完成 grade；当前不具备可用性。

## 关键观察
1. **Doubao 可跑通但耗时长**，主要时间消耗在 vision/LLM 阶段。
2. **Qwen3 vision 超时**（240s），导致整个 grade 失败。
3. `judgment_basis` 已稳定在 **2–5 条**（当前为 3 条）。
4. **视觉事实解析失败仍存在**，并且 warnings 有重复。
5. Chat 能返回内容，但不一定与当前图像题一致（需进一步核对题目定位）。

## Streaming 变更说明
- Demo UI 已改为 **内容分块流式输出**：grade 完成后将报告分块写入 assistant 消息（用户体验上为逐步出现的文本）。
- 该流式是“最终内容分块流式”，不是 LLM token 级别流式；若需要 token 级别流式需改后端 SSE + LLM streaming。

## 后续建议（基于本次测试）
1. **默认使用 Doubao**（Qwen3 目前不可用）。
2. 排查视觉事实解析失败原因（Vision 输出未包含 JSON 或 marker 未命中）。
3. 去重 warnings，避免重复信息影响用户体验。
4. 若继续降低耗时：建议先对上传图片做压缩/缩图，减少模型 URL 拉取失败与超时。
