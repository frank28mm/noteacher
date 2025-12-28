# 开发对齐指南

本指南用于约束开发流程，确保与需求/契约保持一致。改动前后请对照执行。

## 基准文档（唯一真源）
- `product_requirements.md`：需求与行为边界（科目范围、苏格拉底模式、坐标规范、严格模式等）。
- `agent_sop.md`：执行流程与技术栈落地（FastAPI+直连 LLM/Vision，不用 SDK；幂等/异步/会话/SSE、安全等）。
- `API_CONTRACT.md`：接口契约（`/grade` `/chat` `/jobs` 请求/响应字段、SSE 事件、错误码、幂等、超时/重试）。
- `docs/autonomous_grade_agent_design.md`：Autonomous Grade Agent 结构设计（ADK 对齐，不依赖 Google 服务）。
- `homework_agent/models/schemas.py`：Pydantic 模型真源（字段名/类型）。
- `implementation_plan.md`：Phase 1 交付范围与依赖。
- `docs/development_rules.md`：工程开发规则（评估门禁 / CI 分阶段 / 成本&时延护栏 / 安全与可观测性 / 回滚）。
- `docs/development_rules_quickref.md`：开发规则速查卡（可执行命令 + checklist）。

## 开发约束
- 不得引入 Claude Agent SDK；仅用 FastAPI + 直接 LLM/Vision API。
- 统一使用归一化 bbox `[ymin, xmin, ymax, xmax]`（原点左上，y向下）。bbox/切片为可选增强：允许为 `null`，但必须在 `warnings` 说明“定位不确定，改用整页”。
- 幂等：通过 `X-Idempotency-Key` 头实现，冲突返回 409。
- 会话/记忆边界：
  - chat 对话历史保留 7 天（定期清理），超期不保证恢复对话；
  - 辅导链默认只读当前 Submission（单次上传）上下文，不读历史画像/历史错题；
  - 报告链可读取历史 submissions + 错题排除记录用于长期分析。
- 题目路由（产品要求）：支持非数字题名（如“思维与拓展/旋转题”）；若无法定位，SSE 必须返回 `question_candidates` 供 UI 按钮选择，禁止继续沿用旧焦点乱讲。
- 同步/异步：小批量尽量同步；预估超时/大批量返回 202+`job_id`，`/jobs/{job_id}` 查询状态。
- 严格模式：英语 strict 模式需关键词提炼+阈值（~0.91）；回退策略按要求执行。
- SSE：心跳 30s，90s 无数据可断开，支持 last-event-id 续接。
- 视觉模型选择：仅允许用户选择白名单值 `doubao`(Ark) / `qwen3`(SiliconFlow)，默认 `doubao`；不向外暴露 OpenAI 视觉选项；后端需验证白名单避免任意 base_url/model 注入。`doubao` 优先公网 URL，但允许 Data-URL(base64) 兜底（绕开 provider-side URL 拉取不稳定）；`qwen3` 支持 URL 或 Data-URL(base64) 兜底。
- LLM/Chat 选择：Phase 1 `/grade` 与 `/chat` 当 provider=ark 时均使用 `ARK_REASONING_MODEL`（当前测试环境可指向 `doubao-seed-1-6-vision-250815`）；`ARK_REASONING_MODEL_THINKING` 不作为必需项。允许在白名单内通过 `llm_model` 做调试切换；不对外新增其他 LLM 选项，避免适配面膨胀。
- MVP 验证策略：当前所有开发以本地测试跑通为先决条件，优先确保在本机环境（含本地存储/缓存）端到端可用，再考虑上线和云端替换。
- 判定输出一致性（新增）：每题必须覆盖，标出学生作答/标准答案/is_correct；选项题写明 student_choice/correct_choice；verdict 仅 correct/incorrect/uncertain；severity 仅 calculation/concept/format/unknown/medium/minor；不确定标记 uncertain，不编造 bbox；`vision_raw_text` 必须返给客户端用于审计；`judgment_basis` 必须输出中文短句依据。
- 题目定位与切片（BBox + Slice，MVP）：bbox 对象为“整题区域（题干+作答）”；允许多 bbox 列表；裁剪默认 5% padding，裁剪前 clamp 到 [0,1]；失败必须回退整页并写 warnings。切片 TTL 必须可配置（例如 24h 或 7d），Demo 可用 public bucket，生产建议 signed URL。
- QIndex 后台任务（BBox/Slice）：不得在 API 主进程内执行图像处理/裁剪/上传等重任务；必须通过 Redis 队列交给独立 worker 处理（`python3 -m homework_agent.workers.qindex_worker`），API 仅 enqueue 并写入 `qindex queued` 占位 warnings。
- QIndex 存储同源（产品化要求）：API 与 worker 必须连接同一个 Redis（同 `REDIS_URL`/`CACHE_PREFIX`），qindex 结果写入 `qindex:{session_id}` 后由 API 读取；无 Redis 时，API 会写入 `qindex skipped: ...` 占位 warnings 以便客户端可解释降级。
- Autonomous Grade Agent（当前实现口径）：/grade 以 `homework_agent/services/autonomous_agent.py` 为主（规划→工具→反思→汇总），在成本/时延护栏内尽量产出可审计的结构化结果；当证据不足或触发护栏时，必须通过 `warnings/needs_review` 明确降级原因，禁止“硬编”。
  - 预处理/切片：作为可选增强（best-effort），不可用时允许跳过，但必须在 `warnings` 说明风险。
  - 可观测性：保留 `agent_plan_start/agent_tool_call/agent_reflect_* /agent_finalize_done` 等日志点位，并把 prompt/model/thresholds/experiment variant 写入 `run_versions` 以便回放与回归。
- 数据保留（产品要求）：
  - 原始图片 + 批改结果 + 识别原文长期保留（除非用户删除或静默 180 天清理）；
  - chat_history 与切片默认 7 天 TTL（需有定时清理策略）。

## 提交前检查清单
- 字段/响应是否与 `API_CONTRACT.md`、`schemas.py` 一致？无多余 key。
- 归一化 bbox 校验通过，必填 url/bbox 字段齐全。
- 幂等/超时/重试逻辑符合契约（409/202/60s 等）。
- 会话与记忆边界未被打破（不读取历史画像）。
- 苏格拉底辅导默认不限轮；递进提示按 interaction_count 循环（轻提示/方向提示/重提示），不做硬性封顶。
- 测试：关键路径路由、schema 验证、SSE 行为（心跳/断线）已覆盖或手动验证。

## 变更流程
- 任何需求/契约变更，先更新基准文档，再落代码。
- 对未覆盖的新增约束，补充到 `agent_sop.md` 与本指南后再实施。
