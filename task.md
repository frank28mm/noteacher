# 开发任务清单（Phase 1 - Agent 核心）

基准文档：product_requirements.md / agent_sop.md / API_CONTRACT.md / models/schemas.py / implementation_plan.md / docs/vision_providers.md。

- [x] 视觉客户端抽象：`services/vision.py` 根据 provider 选择 silicon/ark，适配 url/base64 输入 → 统一识别结果结构。
- [x] FastAPI 路由骨架（stub）：
  - `/grade` 返回占位，待接入 vision+LLM、幂等/异步逻辑。
  - `/jobs/{job_id}` 查询占位。
  - `/chat` SSE 占位。
- [x] FastAPI 应用骨架：main.py + CORS 中间件。
- [ ] 配置同步：环境读取逻辑（`vision_provider` 白名单）；测试占位：基础路由校验、SSE 心跳事件、vision provider 白名单校验（测试命令未跑，python 不可用）。

## 已完成
- [x] Schema 对齐：`GradeRequest` 增加 `vision_provider`（白名单 qwen3/doubao，默认 qwen3）。
- [x] 配置模板：新增 `.env.template` 与 `.env.example` 对齐的视觉模型配置占位。
- [x] P0 决策与接口契约敲定（需求、SOP、API_CONTRACT、schemas 真源建立）。
- [x] 视觉模型文档 `docs/vision_providers.md`，白名单 qwen3/doubao，默认 qwen3，环境变量示例。

## 备注
- 不使用 Claude Agent SDK；仅 FastAPI + 直接 LLM/Vision API。
- 坐标归一化 `[ymin, xmin, ymax, xmax]` 必填；会话 24h，辅导链只读当前批次。***
