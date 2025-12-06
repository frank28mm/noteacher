# 开发对齐指南

本指南用于约束开发流程，确保与需求/契约保持一致。改动前后请对照执行。

## 基准文档（唯一真源）
- `product_requirements.md`：需求与行为边界（科目范围、苏格拉底模式、坐标规范、严格模式等）。
- `agent_sop.md`：执行流程与技术栈落地（FastAPI+直连 LLM/Vision，不用 SDK；幂等/异步/会话/SSE、安全等）。
- `API_CONTRACT.md`：接口契约（`/grade` `/chat` `/jobs` 请求/响应字段、SSE 事件、错误码、幂等、超时/重试）。
- `homework_agent/models/schemas.py`：Pydantic 模型真源（字段名/类型）。
- `implementation_plan.md`：Phase 1 交付范围与依赖。

## 开发约束
- 不得引入 Claude Agent SDK；仅用 FastAPI + 直接 LLM/Vision API。
- 统一使用归一化 bbox `[ymin, xmin, ymax, xmax]`，输出必须含 page/slice url + bbox（若缺需注明原因）。
- 幂等：通过 `X-Idempotency-Key` 头实现，冲突返回 409。
- 会话：session 24h，辅导链只读当前批次上下文，不读历史画像；长期画像仅写入不读取。
- 同步/异步：小批量尽量同步；预估超时/大批量返回 202+`job_id`，`/jobs/{job_id}` 查询状态。
- 严格模式：英语 strict 模式需关键词提炼+阈值（~0.91）；回退策略按要求执行。
- SSE：心跳 30s，90s 无数据可断开，支持 last-event-id 续接。
- 视觉模型选择：仅允许用户选择白名单值 `qwen3`(SiliconFlow) / `doubao`(Ark)，默认 `qwen3`；不向外暴露 OpenAI 视觉选项；后端需验证白名单避免任意 base_url/model 注入。

## 提交前检查清单
- 字段/响应是否与 `API_CONTRACT.md`、`schemas.py` 一致？无多余 key。
- 归一化 bbox 校验通过，必填 url/bbox 字段齐全。
- 幂等/超时/重试逻辑符合契约（409/202/60s 等）。
- 会话与记忆边界未被打破（不读取历史画像）。
- 苏格拉底 5 轮上限与提示递进实现到位。
- 测试：关键路径路由、schema 验证、SSE 行为（心跳/断线）已覆盖或手动验证。

## 变更流程
- 任何需求/契约变更，先更新基准文档，再落代码。
- 对未覆盖的新增约束，补充到 `agent_sop.md` 与本指南后再实施。
