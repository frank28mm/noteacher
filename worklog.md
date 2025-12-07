# 工作日志（2025-12-07）

## 今日完成
- Vision 防呆与重试：Qwen3 base64 保留 data:mime 前缀；Doubao 仅 URL，入口校验 URL/20MB/Doubao+base64 拒绝；重试日志带 provider/model/operation。
- LLM 重试：网络/超时重试 3 次，RateLimit fail-fast，日志带上下文，移除无用参数；修复 ark 模型配置引起的 404。
- Demo UI 重写：支持 URL/文件上传，Qwen3 base64 兜底、20MB 校验、错题多选、5 轮提示；端口 7890；文案强调 URL 优先、Doubao 仅 URL。
- 文档对齐：README/API_CONTRACT/task 等注明上传策略、RateLimit 行为、Gradio 计划。pytest 全通过。

## 当前状态
- Qwen3 路径：URL/本地上传可用，非数学图返回“全对/无数学内容”。
- Doubao 路径：URL 可用（需正确 MODEL_REASONING，像素 < ~36MP），非数学图返回泛化描述。
- Demo 可运行（需避开端口占用）；仍直调用客户端，未走后端路由。
- 未接入：Redis/队列持久化，异步批处理，RateLimit Retry-After 处理。

## 待解决/风险
- Demo 与真实接口逻辑有差异（未走 /api/v1/grade/chat）。
- 异步/队列、会话持久化未落地；RateLimit 仅 fail-fast。
- Doubao 分辨率上限需在 UI/文档明确，避免 400。

## 下一步计划
1) 用真实数学/英语作业图做端到端验证，确认结构化输出/辅导上下文。
2) 可选：Demo 改为调用后端 /api/v1/grade 和 /api/v1/chat，减少行为差异。
3) 工程化收尾：接入 Redis/队列、完善异步和会话持久；如需，增加 RateLimit 提示或 Retry-After 支持。
