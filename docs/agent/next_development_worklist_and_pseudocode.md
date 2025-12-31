# Next Development Worklist & Pseudocode（留档）

> 目的：把今天基于 5 份白皮书产出的“分析/规则”，转成下一阶段**可执行的工作清单 + 可落地的伪代码**，用于指导你们在不扩张适配面的前提下，让 agent 变得更可靠、更聪明，并且可回归、可观测、可控成本。

---

## 0. 决策依据（对齐的需求与目标）

本计划以仓库的“真源/基准文档”为决策依据（优先级从高到低）：

1. `product_requirements.md`：产品需求边界（科目范围、苏格拉底模式、坐标规范、严格模式等）。
2. `homework_agent/API_CONTRACT.md`：对外契约（字段、错误码、幂等、超时/重试、SSE 事件等）。
3. `agent_sop.md`：执行流程与落地约束（FastAPI + 直连 LLM/Vision；会话/记忆边界；降级策略等）。
4. `docs/engineering_guidelines.md`：工程约束与“唯一真源”入口。
5. `docs/development_rules.md` + `docs/development_rules_quickref.md`：工程化规则（门禁/日志/回滚/安全/可观测性）。

并参考今天形成的 5 份分析文档（用于解释“为什么做/先做什么”）：
- `docs/agent/agent_architecture_analysis.md`
- `docs/agent/agent_context_analysis.md`
- `docs/agent/agent_mcp_analysis.md`（已决定现阶段不做 MCP，只保留必要规范）
- `docs/agent/agent_quality_analysis.md`
- `docs/agent/prototype_to_production_analysis.md`

### 本阶段目标（按重要性）

1. **质量门禁（Evaluation‑Gated）**：任何行为变更（prompt/模型/工具策略/阈值）都能被 replay 回归捕捉。
2. **成本/时延可控**：tokens、耗时、迭代次数有口径、有上限、有退避策略、有降级路径。
3. **可观测性与可回滚**：生产排障不靠“猜”；回滚不靠“祈祷”。
4. **“更聪明”的迭代可持续**：每次只改一个点，能解释、能验证、能复盘（Observe→Act→Evolve）。

### 约束（明确不做/后置）

1. **不做 MCP 接入**（现阶段）：只采用我们已收敛的工具规范（schema/ToolResult/错误字段/HITL/日志/净化）。
2. **不提前锁死部署形态**：Canary/K8s/Prometheus/Grafana/OTel/Jaeger 等后置到 P2（规模上来再做更划算）。

---

## 1. 工作清单（Worklist）

> 说明：每项包含：为什么做 → 交付物 → 验收标准 → 伪代码/接口草案。

### P0‑Product（1–2 周）：把“错题→复盘→报告”闭环打通到可用

#### WL‑P0‑010：错题本 MVP（历史检索 + 排除/恢复 + 知识点基础统计）

**为什么**：闭环不是“批改一次就结束”，必须能沉淀错题、允许纠偏、支持长期复盘。

**实施方案（Design Doc）**：`docs/design/mistakes_reports_learning_analyst_design.md`

**交付物**：
- 数据层：`submissions`（批改快照）+ `mistake_exclusions`（排除语义）可回滚迁移（`migrations/*.sql`）
- API：
  - `GET /mistakes`：按 `user_id` 聚合历史错题
  - `POST /mistakes/exclusions`：排除误判
  - `DELETE /mistakes/exclusions/{submission_id}/{item_id}`：恢复错题
  - `GET /mistakes/stats`：按 `knowledge_tags` 聚合（MVP）

**验收标准**：
- 不依赖 Redis 也能查询历史错题（以 submission 快照为真源）
- 排除/恢复只影响统计/报告，不修改历史事实
- 有契约文档与最小测试覆盖

---

### P0（1–2 周）：把“可回归 + 可观测 + 可控”做成日常

#### WL‑P0‑001：Replay Golden Set v0 扩充（最优先）

**为什么**：没有稳定样本集，“变聪明”无法验证，线上问题会逼着补。

**交付物**：
- 扩充离线回归样本 `homework_agent/tests/replay_data/samples/`（建议 20–30 个）
- 可选（若选择“不入库”）：维护本机私有样本清单 `homework_agent/tests/replay_data/samples_inventory.csv`（仅保存绝对路径+标签，不提交图片）
- 每个样本包含：输入图片 + 期望结构（或 judge 口径）+ 元信息（subject、难度、是否允许 uncertain）

**验收标准**：
- `python3 -m pytest homework_agent/tests/test_replay.py -v` 不跳过（至少跑到 1 个 case）
- 覆盖：清晰/模糊、单题/多题、几何图、OCR 低质量、跨学科干扰、空白/缺答等

**伪代码（样本 schema 建议）**：
```python
# homework_agent/tests/replay_data/samples/<case_id>.json (建议)
{
  "case_id": "math_geo_001",
  "subject": "math",
  "input": {
    "or_base64": "<redacted_or_base64_blob_optional>",
    "local_images": ["/abs/path/to/private/image.jpg"],  # optional: 不入库时本地跑
    "image_urls": ["https://..."],  # optional: 未来可接私有 URL
  },
  "expect": {
    # 最小可验证：结构与关键字段（不要一开始就追 correctness 全覆盖）
    "must_have_fields": ["questions", "summary", "wrong_count", "warnings"],
    "must_cover_all_questions": true,
    "allow_uncertain": true,
    "max_wrong_count": 10
  },
  "tags": ["geometry", "low_ocr"],
  "notes": "用于回归：图形题+OCR偏糊"
}
```

---

#### WL‑P0‑002：把 replay + metrics 变成 PR 日常门禁（轻门禁 → 严门禁）

**为什么**：只跑 `pytest -q` 不足以约束 agent 行为变更；要把“行为回归”变成 PR 默认门禁。

**交付物**：
- CI：PR 阶段跑 replay + metrics（轻门禁，不做 baseline 阻断或只允许 missing baseline）
- main 阶段（或手工触发）跑 baseline 阻断（严门禁）

**验收标准**：
- PR 里改了 prompt 或 agent 策略，CI 能自动产出 `qa_metrics/metrics_summary.json`
- 有 baseline 时能阻断明显回归；无 baseline 时可先不阻断但给出告警

**伪代码（门禁流程）**：
```python
def ci_quality_gate():
    # 1) replay tests (schema + minimal invariants)
    run(["python3", "-m", "pytest", "homework_agent/tests/test_replay.py", "-v"])

    # 2) metrics summary (offline)
    run(["python3", "scripts/collect_replay_metrics.py", "--output", "qa_metrics/metrics.json"])

    # 3) regression check (optional in PR)
    run([
        "python3", "scripts/check_baseline.py",
        "--current", "qa_metrics/metrics_summary.json",
        "--baseline", ".github/baselines/metrics_baseline.json",
        "--threshold", "0.05",
        "--allow-missing-baseline",
    ])
```

---

#### WL‑P0‑003：全链路关联字段贯通（request_id/session_id/iteration/stage）

**为什么**：没有稳定关联字段，生产排障/评估回放成本极高；同时 metrics 也无法按“同一请求链路”汇总。

**交付物**：
- FastAPI middleware：为每个请求生成/传播 `request_id`（优先复用 header，如 `X-Request-Id`，否则生成）
- 关键 `log_event` 与 tool 调用都必须带 `request_id`、`session_id`、`stage`、`iteration`
- `scripts/check_observability.py` 从 best-effort 升级为“关键路径 strict”（可按目录/文件白名单）

**验收标准**：
- 任意一次 `/grade` 或 autonomous run 的日志中，能用 `request_id` 聚合出完整的链路关键事件
- 关键日志事件：`agent_plan_start / agent_tool_call / agent_tool_done / agent_finalize_done` 至少齐全

**伪代码（middleware + context 注入）**：
```python
# homework_agent/api/middleware/request_context.py (建议实现)
from contextvars import ContextVar
import time
import uuid

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
session_id_var: ContextVar[str] = ContextVar("session_id", default="")

def get_request_id() -> str:
    return request_id_var.get() or ""

async def request_context_middleware(request, call_next):
    rid = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex}"
    # session_id: 优先来自 API contract / body / cookie
    sid = extract_session_id(request)  # project-specific

    token1 = request_id_var.set(rid)
    token2 = session_id_var.set(sid)
    start = time.time()
    try:
        resp = await call_next(request)
        return resp
    finally:
        duration_ms = int((time.time() - start) * 1000)
        log_event(logger, "http_request_done",
                  request_id=rid, session_id=sid,
                  path=str(request.url.path),
                  method=str(request.method),
                  duration_ms=duration_ms)
        request_id_var.reset(token1)
        session_id_var.reset(token2)
```

---

#### WL‑P0‑004：成本/时延护栏（usage/tokens + budget + timeout + backoff）

**为什么**：agent 的成本/时延不可预测是“独特风险”；必须先有口径与硬上限，才能放心迭代智能。

**交付物**：
- 每次 LLM 调用：记录 `provider/model/prompt_version/usage(prompt/completion/total)/duration_ms/stage`
- 配置化阈值：`max_iterations / per_stage_timeout / total_budget_tokens / total_budget_ms`
- 退避策略：超时/429/5xx 做有限重试；达到上限后降级或 `needs_review`

**验收标准**：
- replay 的 `metrics_summary.json` 能反映 tokens 与 p95 延迟趋势（至少日志里能抓到）
- 超预算/超时能够稳定触发降级/needs_review（不崩溃、不无限重试）

**伪代码（LLM call wrapper）**：
```python
async def call_llm_with_budget(*, stage: str, prompt: str, budget, request_ctx):
    start = now_ms()
    try:
        with timeout(budget.per_stage_timeout_ms[stage]):
            result = await llm_client.generate(prompt=prompt, model=budget.model)
        # result.usage: {"prompt_tokens":..., "completion_tokens":..., "total_tokens":...}
        log_llm_usage(logger,
                      request_id=request_ctx.request_id,
                      session_id=request_ctx.session_id,
                      provider=budget.provider,
                      model=budget.model,
                      usage=getattr(result, "usage", {}) or {},
                      stage=stage)
        budget.consume(tokens=result.usage.total_tokens, ms=now_ms()-start)
        return result
    except TimeoutError as e:
        log_event(logger, "llm_timeout",
                  request_id=request_ctx.request_id,
                  session_id=request_ctx.session_id,
                  stage=stage,
                  error=str(e),
                  error_type="TimeoutError")
        if budget.can_retry(stage):
            await sleep(backoff_ms(budget.retry_count(stage)))
            return await call_llm_with_budget(stage=stage, prompt=prompt, budget=budget, request_ctx=request_ctx)
        return ToolResult.error(
            error_type="LLM_TIMEOUT",
            retryable=False,
            fallback_used="needs_review",
        )
```

---

#### WL‑P0‑005：工具层统一契约（ToolResult + 错误恢复字段 + 输出净化 + HITL）

**为什么**：动态工具编排是 agent 的独特风险；工具越多越容易“部分失败/脏输出/不可恢复”。

**交付物**：
- ToolResult 统一结构（成功/失败都返回），包含：
  - `ok`, `data`, `error_type`, `error_code`, `retryable`, `fallback_used`, `warnings`, `needs_review`
  - `timing_ms`, `stage`, `tool_name`, `request_id`, `session_id`
- 输出净化（输出到日志/持久化/返回给用户前）：
  - 秘钥/签名/URL token 脱敏
  - PII 探测（手机号/邮箱/学号/身份证等）→ 触发 `needs_review`
- HITL 触发规则落地：只要满足条件就 `needs_review`（并写明 `warning_code`）

**验收标准**：
- 任意 tool 的异常不会导致 agent 崩溃；而是产生可统计的 `ToolResult(ok=false, ...)`
- 任何 `needs_review` 都带 machine-readable `warning_code`

**伪代码（ToolResult + 执行包装）**：
```python
class ToolResult:
    def __init__(self, *, ok: bool, data=None, warnings=None,
                 error_type=None, error_code=None, retryable=False,
                 needs_review=False, fallback_used=None,
                 tool_name=None, stage=None, timing_ms=None,
                 request_id=None, session_id=None):
        ...

    @staticmethod
    def success(**kw): return ToolResult(ok=True, **kw)
    @staticmethod
    def error(**kw): return ToolResult(ok=False, **kw)

async def run_tool(tool_fn, *, tool_name: str, stage: str, args: dict, request_ctx, policy):
    start = now_ms()
    try:
        log_event(logger, "agent_tool_call",
                  request_id=request_ctx.request_id,
                  session_id=request_ctx.session_id,
                  stage=stage, tool=tool_name,
                  args=sanitize_for_log(args))

        raw = await tool_fn(**args)
        safe = sanitize_tool_output(raw)
        warnings = []
        if detect_pii(safe):
            warnings.append("pii_detected")
        needs_review = should_needs_review(tool_name=tool_name, stage=stage, output=safe, warnings=warnings)

        tr = ToolResult.success(
            data=safe,
            warnings=warnings,
            needs_review=needs_review,
            tool_name=tool_name, stage=stage,
            timing_ms=now_ms() - start,
            request_id=request_ctx.request_id,
            session_id=request_ctx.session_id,
        )
        log_event(logger, "agent_tool_done", **tool_result_to_log_fields(tr))
        return tr
    except Exception as e:
        tr = ToolResult.error(
            error_type=e.__class__.__name__,
            error_code=classify_tool_error(e),
            retryable=is_retryable(e),
            fallback_used=policy.fallback_for(tool_name),
            needs_review=True,
            warnings=["tool_exception"],
            tool_name=tool_name, stage=stage,
            timing_ms=now_ms() - start,
            request_id=request_ctx.request_id,
            session_id=request_ctx.session_id,
        )
        log_event(logger, "agent_tool_error", **tool_result_to_log_fields(tr))
        return tr
```

---

#### WL‑P0‑006：Prompt/模型/阈值“可追溯 + 可回滚”闭环

**为什么**：你们已有 prompt version，但若运行时不写日志、不可审计，就无法回放/定位回归。

**交付物**：
- prompt：修改 `homework_agent/prompts/*.yaml` 必须递增 `version`（已在 rules 中）
- 运行时日志：记录 `prompt_id/prompt_version/provider/model/thresholds_hash`
- 回滚策略：P0 用 `git revert`（P2 再做运行时选择版本/灰度）

**验收标准**：
- 任何一次输出都能追溯到“使用了哪个 prompt + 哪个模型 + 哪组阈值”
- 线上问题能用 `request_id` 找到对应版本信息

**伪代码（版本记录）**：
```python
def log_run_versions(request_ctx, *, prompt_meta, model_meta, thresholds):
    log_event(logger, "run_versions",
              request_id=request_ctx.request_id,
              session_id=request_ctx.session_id,
              prompt_id=prompt_meta.id,
              prompt_version=prompt_meta.version,
              provider=model_meta.provider,
              model=model_meta.model,
              thresholds=sanitize_for_log(thresholds))
```

---

### P1（2–4 周）：让“更聪明”的改动可被评估、可被周报驱动

#### WL‑P1‑010：学情分析报告（Report Jobs + 学情分析师 subagent）

**为什么**：报告是“复盘→运营”的核心交付物，必须从 grade/chat 解耦为独立链路（异步、可重跑、可审计）。

**实施方案（Design Doc）**：`docs/design/mistakes_reports_learning_analyst_design.md`

**交付物**：
- 数据表（建议）：
  - `report_jobs`：异步任务（pending/running/done/failed）
  - `reports`：报告内容（JSON + 可读摘要），可按 `user_id/time_range` 查询
- Subagent（学情分析师）：
  - 输入：一段时间范围内 submissions（含 wrong_items/knowledge_tags/severity/judgment_basis）+ `mistake_exclusions`
  - 输出：结构化报告（薄弱点 TopN、错误类型画像、趋势、复习建议、7/14 天计划）+ evidence refs
- API（建议）：
  - `POST /reports` 创建任务
  - `GET /reports/{report_id}` 查询
  - `GET /reports?user_id=...` 列表

**验收标准**：
- 报告生成不阻塞主请求；失败可重跑；产物可追溯到输入 submissions
- 报告输出字段固定（schema），并可用回归样本评估（避免 prompt 漂移）

#### WL‑P1‑001：Baseline 阈值治理（从“允许缺失”→“强阻断”）

**交付物**：
- baseline 文件（建议：`.github/baselines/metrics_baseline.json`）正式提交
- 更新流程：谁可更新、需要哪些证据（replay 报告 + 解释）

**验收标准**：
- baseline 生效后，success_rate/uncertain_rate/p95_latency 任何显著回归都会被阻断

---

#### WL‑P1‑002：离线周报（Observe→Act→Evolve 的“Observe”）

**交付物**：
- 周报产物：`metrics_summary.json` + `report.html`（可先放 artifacts 或仓库外存储）
- 结构：趋势、Top 回归 case、Top tokens/latency case、needs_review 占比

**伪代码（周报生成）**：
```python
def weekly_report(summaries: list[dict]) -> dict:
    trend = compute_trend(summaries)
    top_slow = top_k(summaries, key="latency.p95_ms")
    top_cost = top_k(summaries, key="tokens.total")
    return {"trend": trend, "top_slow": top_slow, "top_cost": top_cost}
```

---

#### WL‑P1‑003：Context Engineering 的低风险增益（先不做“长记忆画像”）

**交付物**：
- session 内“结构化摘要”与“可回放上下文”能力（TTL + 上限）
- 只读边界：不引入历史画像读取（符合 `agent_sop.md`）

**伪代码（session memory）**：
```python
class SessionMemory:
    def __init__(self, *, ttl_s: int, max_turns: int, max_tokens: int):
        self.ttl_s = ttl_s
        self.max_turns = max_turns
        self.max_tokens = max_tokens

    def append_turn(self, session_id: str, turn: dict):
        store.append(session_id, turn, ttl=self.ttl_s)
        if store.turn_count(session_id) > self.max_turns:
            self.summarize(session_id)

    def summarize(self, session_id: str):
        turns = store.load_recent(session_id, limit=self.max_turns)
        summary = summarizer(turns)  # LLM or deterministic summarizer
        store.save_summary(session_id, summary, ttl=self.ttl_s)

    def build_context(self, session_id: str) -> dict:
        return {"summary": store.load_summary(session_id),
                "recent_turns": store.load_recent(session_id, limit=10)}
```

---

#### WL‑P1‑004：Grade 异步任务 Worker 化（路线 B）

**为什么**：当前大批量异步批改使用 FastAPI `BackgroundTasks`，在多实例/滚动发布/重启场景下不可恢复；`/jobs/{job_id}` 也需要跨实例一致。

**交付物**：
- 新增 `grade_queue`：Redis 队列 + job 状态存储（沿用 cache_store 口径），包含 enqueue/store/get
- 新增 `grade_worker`：BRPOP 消费 `grade:queue`，执行 `perform_grading()`，写回 `job:{job_id}`
- `/api/v1/grade`：大批量分支改为 enqueue（不再使用 BackgroundTasks）
- `/api/v1/jobs/{job_id}`：读取同一份 job 状态（任意实例一致）

**验收标准**：
- API 多实例下：任意实例都能查询同一 `job_id` 状态
- worker 重启后可继续消费队列；API 重启不丢任务状态
- 幂等键命中时不重复 enqueue；参数不一致仍返回 409

**伪代码（最小闭环）**：
```python
# services/grade_queue.py
@dataclass(frozen=True)
class GradeJob:
    job_id: str
    request_id: str
    session_id: str
    user_id: str
    provider: str
    enqueued_at: float

def enqueue(job: GradeJob, *, req_payload: dict) -> None:
    cache.set(
        f"job:{job.job_id}",
        {"status": "processing", "created_at": iso_now(), "result": None},
        ttl_seconds=24 * 3600,
    )
    cache.set(f"jobreq:{job.job_id}", req_payload, ttl_seconds=24 * 3600)
    redis.lpush("grade:queue", job.job_id)

def get_job(job_id: str) -> dict | None:
    return cache.get(f"job:{job_id}")
```
```python
# workers/grade_worker.py
while True:
    job_id = redis.brpop("grade:queue")
    payload = cache.get(f"jobreq:{job_id}")
    if not payload:
        continue
    try:
        cache.set(f"job:{job_id}", {**cache.get(f"job:{job_id}"), "status": "running"})
        result = await perform_grading(
            GradeRequest(**payload["grade_request"]), payload["provider"]
        )
        cache.set(
            f"job:{job_id}",
            {"status": "done", "result": result.model_dump(), "finished_at": iso_now()},
            ttl_seconds=24 * 3600,
        )
    except Exception as e:
        cache.set(
            f"job:{job_id}",
            {"status": "failed", "error": str(e), "finished_at": iso_now()},
            ttl_seconds=24 * 3600,
        )
```

---

#### WL‑P1‑005：模型 B（FastAPI 唯一入口）与生产安全开关

**为什么**：产品方向是“前端只调用本服务 API”；开发期 Supabase 只是临时实现，后续要可替换到国内云 DB/OSS。需要先固化安全边界与配置护栏，避免 dev 配置误上公网。

**交付物**：
- 文档明确：模型 B = 前端不直连 DB/Storage；所有访问都走 FastAPI
- 生产配置护栏（fail-fast）：
  - `APP_ENV=prod` 时强制 `AUTH_REQUIRED=1`
  - 生产 CORS 必须显式 allowlist（不允许 `*`）
- 存储策略抽象（为未来替换供应商做准备）：
  - `StorageBackend.upload(...) -> object_key`
  - `StorageBackend.sign_url(object_key, expires_s) -> signed_url`

**验收标准**：
- 前端不需要 Supabase key（或未来云厂商 key）
- API 层可通过 `Authorization` 唯一确定 `user_id`，所有读写按 `user_id` 隔离

**伪代码（存储抽象）**：
```python
class StorageBackend(Protocol):
    def upload_file(self, *, user_id: str, upload_id: str, local_path: str) -> list[str]: ...
    def sign_url(self, *, object_key: str, expires_s: int) -> str: ...

def upload_endpoint(file):
    keys = storage.upload_file(user_id=user_id, upload_id=upload_id, local_path=tmp_path)
    urls = [storage.sign_url(object_key=k, expires_s=900) for k in keys]
    return {"upload_id": upload_id, "page_keys": keys, "page_image_urls": urls}
```

---

### P2（1–2 月）：规模化工程（灰度/告警/平台监控/Reviewer 工具）

只在确有上线与规模需求时再推进：
- Canary/Feature flags/AB
- 平台化监控（OTel/Prometheus/Grafana/Jaeger）与告警
- 安全响应演练 + postmortem 机制
- Reviewer UI/工作台（聚合 needs_review、回放轨迹、标注回收进 replay）

---

## 2. “更聪明”的开发方式（每轮迭代模板）

> 核心原则：**一次只改一个变量**，其余保持不变；以 replay+metrics 判断收益与风险。

### Iteration Template（每 3–5 天一轮）

1. 选一个改善点（只能选 1 个）：prompt / 工具策略 / 解析鲁棒性 / 自检与降级 / context 构造
2. 为该改善点补 replay case（至少 2 个：正常 + 失败/边界）
3. 跑 replay+metrics：对比 baseline 与上次迭代
4. 若回归：必须能用日志（request_id + versions）定位原因
5. 若收益：将新失败 case 纳入 Golden Set（飞轮）

**伪代码（迭代门禁）**：
```python
def iteration_gate(change):
    assert change.has_replay_cases()
    before = load_baseline()
    after = run_replay_and_collect_metrics()
    assert regression_check(before, after).passed()
    return "merge_ok"
```

---

## 3. 关键“需要落地到代码”的接口清单（仅草案，不在本次实现）

> 这一节列出后续编码时建议新增/统一的接口，以便你们分工。

### 3.1 RequestContext（贯穿全链路）
```python
class RequestContext:
    request_id: str
    session_id: str
    user_id: str | None
    subject: str
    iteration: int
    stage: str
```

### 3.2 SafetySignals（可机器统计）
```python
class SafetySignals:
    needs_review: bool
    warning_codes: list[str]  # e.g. ["pii_detected", "prompt_injection_suspected"]
    degraded: bool
    degraded_reason: str | None
```

### 3.3 ToolPolicy（统一重试/降级/HITL）
```python
class ToolPolicy:
    max_retries: dict[str, int]
    fallback_map: dict[str, str]  # tool_name -> fallback tool / "skip" / "whole_page"
    hitl_rules: list  # predicates -> warning_code
```

---

## 4. Definition of Done（完成定义）

当你们开始实际编码时，建议以以下 DoD 判断“这一阶段是否完成”：

- P0：PR 默认能跑 replay+metrics（样本不为空），关键日志能按 request_id 串起来，LLM usage 记录齐全，超时/预算能触发降级与 needs_review。
- P1：baseline 阻断正式启用，周报能驱动回归修复，context 增益不破坏记忆边界。
- P2：有灰度/告警/Reviewer 工具链，安全响应流程可演练，线上问题能被快速止血与回滚。
