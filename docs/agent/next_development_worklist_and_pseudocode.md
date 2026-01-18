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

### 本轮复盘 → 流程护栏（输入质量 + 作答存在性）（从 #424359 复盘）

> 背景：`#424359` 出现“未作答却判 correct”（选择题括号占位 `（ ）` 被 OCR/模型误读成 `（A）`，再被当作 `student_answer='A'`）。  
> 目标：把问题从“单点修 bug”升级为“流程层保证”——即使未来更多用户、更多噪声，也能稳定兜住。

**我们要做的不是**：为某一道题写特判。  
**我们要做的是**：建立两道保障——事前引导 + 事后兜底（并配 replay/观测）。

1) **事前引导（Frontend）**：在拍照/预览/上传关键页提示“清晰/明亮/整洁”，并为首次用户提供 1 次性教程动效  
2) **事后兜底（Backend）**：统一“作答存在性”门禁（空白必错 + 选择题占位误读纠偏），并对历史记录做 best‑effort 修复  
3) **可观测 + 可回归（Backend/QA）**：把这类 case 写进 replay（低质量/OCR 噪声/空白题），确保以后不会回归  
4) **可纠正（Frontend）**：用户可一键改判（对题/错题/待定）并立即体现在统计/报告中（已有链路继续完善）

### Frontend‑H5（对齐 `docs/frontend_design_spec_v2.md`）：执行 Backlog（不另开文档）

> 说明：前端的页面命名/跳转/文案规则以 `docs/frontend_design_spec_v2.md` 为唯一真源；本文只作为“可执行拆解清单”。  
> 核心冻结：拟态阴影 **全站统一 tokens**；Primary CTA 统一为 `START`；底部导航中英全切换；编号永远 `#` 前缀；HOME/Back 规则按真源 §2。

#### FE‑P0（先做：避免全局返工）

- FE‑P0‑01 统一 Shadow Tokens v1（全站拟态统一，含 `shadowRaised/Pressed/Inset/Icon`）（0.5–1d）
  - 验收：Home/题目详情/报告详情三页对照截图观感一致；全站只使用这一套 tokens。
- FE‑P0‑02 文字体系落地（按真源 `§1.6 Copy & Typography Rules` 的锚点与中英文案）（0.5–1d）
  - 验收：Page Title/Section Header/Subheader/Card Title/Primary CTA/Empty/Warning/Error/Success 全命中；中文全中文、英文全英文。
- FE‑P0‑03 路由骨架 + HOME/Back 规则（1d）
  - 验收：`AI辅导/登录注册/订阅/历史筛选弹窗` 无 HOME；其它页面按真源显示 HOME 或 Back。
- FE‑P0‑04 API Client 对齐（`/api/v1` + 401/错误统一处理）（0.5–1d）
  - 验收：任何 401 必然进入登录流；错误提示文案使用真源 §1.6.4。
- FE‑P0‑05 Job 轮询状态机（不误判失败，使用 `elapsed_ms`，降频轮询）（1–1.5d）
  - 验收：超时不进入错误页；仍持续追更直到后端 `job.status=done/failed`；策略满足真源 §4.1（2s/5s/10s + max_wait）。

- FE‑P0‑06 配额 UX（余额展示 + 402 配额不足引导订阅）（✅ 已完成）
  - 证据（前端仓库 `noteacher-frontend`）：
    - `src/services/api.ts`（402 interceptor：保存 `last_quota_error` 并跳转 `/subscribe?reason=quota`）
    - `src/hooks/useQuota.ts`（拉取 `GET /api/v1/me/quota`）
    - `src/pages/Home.tsx` / `src/pages/Mine.tsx`（显示 `CP/COUPON`）
    - `src/pages/Subscribe.tsx`（展示配额不足原因提示）
  - 验收：当后端返回 402（配额不足）时，前端自动跳转订阅页并明确提示原因；Home/Mine 余额可见。

- FE‑P0‑07 SSE 续接（Last‑Event‑Id 断线重连 + 不重复输出）（🟡 未完成）
  - 现状：已支持 fetch+ReadableStream SSE 流式（`src/pages/AITutor.tsx`），但未实现自动重连与 `Last-Event-Id` 续接。
  - 验收：网络断开/刷新后能自动恢复 SSE；请求带 `Last-Event-Id`；UI 不重复 append 历史段落。

#### FE‑P1（主链路：先“能跑通且符合流程”）

- FE‑P1‑01 拍照页（H5 先用 `<input capture>`；不追求原生相机取景框能力）（1d）
- FE‑P1‑02 预览/上传 → 自动进入批改（无“提交批改”按钮；固定 `X-Force-Async: 1`）（1d）
- FE‑P1‑03 批改结果（逐页披露页）（1–2d）
  - 验收：Page1 先出即可点题/问 AI；Page2/3 后台逐页补齐（真源 §3.1/§4.2）。
- FE‑P1‑04 批改结果（汇总/最终页）（1d）
  - 验收：整单 done 后进入；题卡可点题/问 AI（真源 §4.3）。
- FE‑P1‑05 题目详情（有图/无图）+ MathRichText（1–2d）
  - 验收：数学推导正文使用真源 §1.6 的 `MathRichText` 锚点（`docs/frontend_ui_page_code.md:1596`/`:1749`）。
- FE‑P1‑06 AI辅导整页（仅 Back，无 HOME；按题上下文；聊天可续）（1–2d）

- FE‑P1‑07 拍照/上传质量提示（清晰/明亮/整洁；不阻塞操作）（0.5d）
  - 为什么：输入质量直接决定 OCR/判定质量；提前提示比事后纠错成本更低。
  - 交付物：
    - `Camera/Preview/Upload` 页统一一行提示（不遮挡操作）：如“尽量光线充足、对焦清晰、卷面完整、背景干净”
    - 可选（P2）：前端轻量质量检测（亮度/模糊/倾斜）仅做 warning，不拦截上传
  - 验收：
    - 拍照页与预览页都能看到一致口径提示；文案按 `docs/frontend_design_spec_v2.md` 的 Copy 规则

- FE‑P1‑08 首次使用教学引导（仅 1 次；可跳过；动效高亮关键按钮）（1d）
  - 为什么：首次用户最容易拍糊/拍暗/拍不全；做一次“怎么拍”能显著降低噪声输入。
  - 交付物：
    - 首次进入拍照流程时出现 3–4 步引导（高亮取景框/相册/确认上传/等待提示），支持“跳过/不再提示”
    - `localStorage` 标记：`onboarding_capture_v1_seen=1`
  - 验收：
    - 仅首次出现；清缓存可复现；不影响老用户速度

#### FE‑P2（数据/历史/分析链路补齐：支撑你新 IA）

- FE‑P2‑01 DATA：错题面板 → 分类面板/列表页 → 题目详情（含“点错题进详情”）（1–2d）
- FE‑P2‑02 DATA：OK 不可逆归档 → 已掌握面板同构（分类→列表→详情→问 AI）（1–2d）
- FE‑P2‑03 HISTORY：批改历史列表（条目显示 `#编号`）（1d）
- FE‑P2‑04 HISTORY：历史作业详情页（快照回放，可继续问 AI）（1–2d）
- FE‑P2‑05 HISTORY：历史筛选弹窗（无 HOME，仅关闭）（0.5–1d）
- FE‑P2‑06 ANALYSIS：科目 + 周期（3/7/30）内嵌筛选（无筛选弹窗）（1d）
- FE‑P2‑07 Start → 报告详情页；报告记录列表条目显示 `#编号`（2d）
- FE‑P2‑08 家庭-子女（Profile）账户切换（Home 头像快捷切换 + 关键流程强提示 + “传错账户”可补救）（1–2d）
  - 状态：✅ 已完成（功能闭环已具备：切换 + 强提示 + 可补救 + 管理）
  - 证据（前端仓库 `noteacher-frontend`）：
    - `src/services/api.ts`：自动注入 `X-Profile-Id`（`active_profile_id`）
    - `src/pages/Home.tsx`：双头像快捷切换（最多显示 2 个 profile），高亮当前并亮绿灯
    - `src/pages/Camera.tsx` / `src/pages/Upload.tsx`：关键流程强提示 `数据库：{profile_name}`
    - `src/pages/ProfileManagement.tsx`：子账号 CRUD（`/me/profiles`）
    - `src/pages/ResultSummary.tsx`：`POST /submissions/{sid}/move_profile`（“移动到其他孩子”可补救）

#### FE‑P3（体验增强：不阻塞主链路；✅ 已完成）

**状态**：✅ 已完成（按你确认：本轮无需再排期；若后续发现回归/缺页，再回到本段补条目）

- FE‑P3‑01 “新页到达”提示（可后置，先保证卡片可靠更新）（0.5–1d）
- FE‑P3‑02 Skeleton / 转场动效（按统一 tokens）（1–2d）

### P0‑Product（1–2 周）：把“错题→复盘→报告”闭环打通到可用

#### WL‑P0‑010：错题本 MVP（历史检索 + 排除/恢复 + 知识点基础统计）

**为什么**：闭环不是“批改一次就结束”，必须能沉淀错题、允许纠偏、支持长期复盘。

**实施方案（Design Doc）**：`docs/archive/design/mistakes_reports_learning_analyst_design.md`

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

#### WL‑P0‑013：历史错题复习（Chat Rehydrate：不依赖 24h TTL）

**为什么**：现阶段 session/qbank 等短期缓存有 24h TTL；用户两天后点历史错题“问老师”不应被迫重新上传，否则体验很差且浪费资源。

**执行计划入口（唯一）**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑A：A‑8）。

**状态**：✅ 已实现并联调通过（后端支持 `submission_id` 复习模式；前端“错题本/历史详情”可直接问老师，无需重新上传）

**交付物**：
- 扩展 `POST /api/v1/chat` 支持“复习模式”（基于 `submission_id + context_item_ids` 从 `submissions` 真源快照重建最小 qbank，并生成新的 `session_id`）
- SSE 首包返回 `session_id`（前端保存后续继续同一会话）
- 回答必须标注证据边界：仅基于该 submission 的证据；证据不足必须 `uncertain/needs_review`

**验收标准**：
- 对 ≥48h 前的 submission，仍能从错题详情进入辅导，不提示“请重新上传/题库快照不存在”
- `submission_id/item_id/session_id` 三者可串联排查（可观测、可审计）

---

#### WL‑P0‑014：作业历史列表（Submissions/History API）

**为什么**：Stitch UI 的 Home “Recent Activity / View all” 与 Report Tab 的历史列表需要权威的“作业记录列表”。此口径必须来自 `submissions`（不能用 `/mistakes` 推断，否则“全对作业”会消失）。

**执行计划入口（唯一）**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑C：C‑5）。

**状态**：✅ 已实现并联调通过（`GET /api/v1/submissions` + `GET /api/v1/submissions/{submission_id}`；Home Recent / 周报页历史区均已接入权威数据源）

**交付物**：
- 新增接口：`GET /api/v1/submissions?subject=math&limit=20&before=...`
- 返回最小字段：
  - `submission_id/created_at/subject/total_pages/done_pages`
  - `summary`（可选）：`total_items/wrong_count/uncertain_count/blank_count/score_text`
  - `session_id`（可选，若仍有效可直接辅导；否则走 WL‑P0‑013 Rehydrate）
- 契约更新：写入 `homework_agent/API_CONTRACT.md` 并补最小测试（确保排序/分页/全对作业可见）

**验收标准**：
- Home 能展示最近 N 次作业（包含全对作业）
- History 列表点击能回放到单次 Result Screen（demo 允许“触发回放 job”方式实现）

**伪代码（查询）**：
```python
def list_submissions(user_id: str, *, subject: str | None, limit: int, before: datetime | None):
    q = db.table("submissions").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(limit)
    if subject:
        q = q.eq("subject", subject)
    if before:
        q = q.lt("created_at", before.isoformat())
    return q.execute()
```

---

#### WL‑P0‑015：作答存在性门禁（空白必错 + 选择题占位误读纠偏）

**为什么**：这是“最基础的正确性”。若“没作答也判对”，用户会直接失去信任；且该类错误会随输入噪声规模化出现。

**状态**：✅ 已落地（2026‑01‑18）

**交付物**：
- 后端统一修正：
  - 选择题括号占位误读（`（ ）` → `（A）`）导致的 `student_answer='A'`：保守回退为 `answer_state=blank` + `verdict=incorrect`
  - 持久化前修复（新作业不再出现），并在 `GET /submissions/{id}` best‑effort 修复历史记录（不触发重批改）
- 题干拼装修正：
  - 把合并在一起的 options（如 `{"A":"3 B.4 C.2 D.1"}`）拆分成标准 `A/B/C/D`，并生成可读的 `question_text`

**验收标准**：
- 对 `#424359`（`upl_4c57d92f0b424359`）Q10：显示为 `未作答` 且 `incorrect`，题干末尾显示 `（  ）`，选项按行展示
- 后续新增作业：不会再出现“空白判对”同类问题（replay 覆盖）

**实现位置（索引）**：
- `homework_agent/utils/submission_store.py`（落库前统一修正）
- `homework_agent/core/qbank_builder.py`（规范化：`answer_state`/`verdict`/warnings）
- `homework_agent/api/submissions.py`（历史 best‑effort 修复 + `question_text`/options 拆分）


### P0（1–2 周）：把“可回归 + 可观测 + 可控”做成日常

#### WL‑P0‑001：Replay Golden Set v0 扩充（最优先）

**为什么**：没有稳定样本集，“变聪明”无法验证，线上问题会逼着补。

**状态**：🔄 已扩充仓库内离线样本到 15 个（text-only，使用 `or_base64` 占位图），并刷新 `.github/baselines/metrics_baseline.json`；仍需逐步补到 20–30 个，并维护私有 inventory（本机绝对路径）做真实 live 回归。

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

**状态**：✅ 已在 `.github/workflows/ci.yml` 默认执行（`pytest` + `test_replay.py` + `collect_replay_metrics.py` + `check_baseline.py`），并已将 `scripts/check_observability.py` 切换为 `--strict`（0 warning 才通过）。

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

#### WL‑P0‑007：/grade 性能拆解与输入策略对比（url/proxy/data_url + image_process）

**为什么**：当前 `/grade` 在 Demo 场景下出现“分钟级耗时”，且与豆包 App 的用户体验差距极大；我们必须先把“慢到底慢在哪”拆成可量化分项，并用可复跑脚本钉住基线，否则后续任何优化/策略切换都不可验证。

**执行计划入口（唯一）**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑A，尤其 A‑2/A‑4）。

**交付物**：
- `/grade` 分项时延口径固化：`grade_total_duration_ms` + `timings_ms`（preprocess/compress/llm/db/queue_wait 等）
- 可复跑脚本：`scripts/bench_grade_variants_async.py`（输出 `docs/reports/grade_perf_variants_*.md/.json`）
- 维度对比（分两档，避免“每次都跑 N=10”拖慢迭代）：
  - 日常迭代：每个 variant 先跑 **N=5**，输出 `p50 + max + 失败率/needs_review率`（用于快速判断方向）
  - 决策/验收：再补一轮 **N=5**（不同时间段/清空队列或隔离前缀），两轮合并视作 **≈N=10**，再看 `p50/p95`
  - `GRADE_IMAGE_INPUT_VARIANT=auto|url|proxy|data_url_first_page|data_url_on_small_figure`
  - `ARK_IMAGE_PROCESS_ENABLED=0/1`
  - `AUTONOMOUS_PREPROCESS_MODE=off|qindex_only|full`
- 实验隔离策略：优先用新的 `CACHE_PREFIX` / `DEMO_USER_ID` 隔离实验（优先级高于 `redis-cli FLUSHDB`）

**验收标准**：
- 在“无排队干扰”（队列为空/隔离前缀）前提下：同一张图 `p50 < 60s`，`p95 < 120s`（以 `grade_total_duration_ms` 为准，且同时记录分项）
- 结论明确：最大慢点来自哪一段，以及下一步默认策略推荐（例如快路径默认 `AUTONOMOUS_PREPROCESS_MODE=qindex_only`，必要时回退 `off`）
- 每次变更都能用相同脚本复跑并在 `docs/reports/` 留档

**最新证据**（URL-only + qindex_only 快路径）：
- `docs/reports/grade_perf_url_n3_fast_finalize_12000_20260102.md`
- `docs/reports/grade_perf_fast_path_summary_20260102.md`
- 视觉题（A‑5，N=5 对比 + 触发规则固化）：`docs/reports/grade_perf_visual_validation_20260102.md`

---

#### WL‑P0‑008：Worker service role key 治理（CI 防泄露 + 运行手册）

**为什么**：worker 需要稳定写库（抢占锁/更新状态/回填事实表），在 RLS 下最可靠的路线是使用 service role；但 service role key 一旦泄露风险极高，因此必须把“只在运行环境使用 + CI 防误提交 + 明确运行手册”变成强约束。

**执行计划入口（唯一）**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑B/WS‑C）。

**状态**：✅ 已落地并验收（worker 运行环境启用 `SUPABASE_SERVICE_ROLE_KEY` + `WORKER_REQUIRE_SERVICE_ROLE=1`；report/facts worker 可稳定写库）

**交付物**：
- 运行手册口径：
  - service role key 只存在于 worker 进程环境变量（Secret Manager/部署平台），**禁止**写入仓库/镜像层/前端
  - API 仍使用 anon key（开发）或 auth（生产），与 worker 权限隔离
- CI 防误提交（已落地，需纳入执行检查）：
  - `scripts/check_no_secrets.py`
  - `.github/workflows/ci.yml` 中强制执行
- Key 轮换预案（最小版本）：发生疑似泄露/误提交时的轮换步骤与影响评估

**验收标准**：
- 任意 PR 都会运行 `python3 scripts/check_no_secrets.py`，且能拦截 `.env/.env.example` 中的 service role key
- worker 在 service role 下可完成：`report_jobs` 抢占锁 + 状态更新 +（如启用）facts 回填写入

---

#### WL‑P0‑009：复核卡（Layer 3）验收闭环（前端阻塞项）

**为什么**：复核卡是“视觉高风险题”的差异化关键能力，也是前端当前验收阻塞点。目标是做到：grade 先完成；少量题进入 `review_pending`；复核完成后卡片升级为 `review_ready/review_failed`，且 UI 可解释、可审计。

**执行计划入口（唯一）**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑A：A‑7.1）。

**状态**：✅ 已闭环验收（前后端口径已对齐：前端不会在 `done` 时提前停止轮询；复核卡可稳定观察到最终态）

**关键对齐点（请前端按此验收）**：
- `question_cards[].card_state`：`review_pending → review_ready/review_failed`
- `question_cards[].review_reasons[]` + `review_summary`：用于 UI 文案与审计
- 轮询策略：**不能在 `job.status=done` 立即停止 polling**；应在“无 `review_pending` 卡片”或“达到 timeout”后停止（否则看不到复核结果）
- 状态口径：后端不存在 `status=reviewing`；复核进度以 `question_cards[].card_state` 表达（避免前端写错字段）

**验收标准**：
- 有 `review_needed` 的卡：≤ 1 次 polling 内进入 `review_pending`
- 复核完成后：≤ 1 次 polling 内进入 `review_ready/review_failed`，并返回 `review_summary/review_reasons`
- 非复核题不受影响：仍为 `verdict_ready`，总体耗时不被全量拖慢

---

#### WL‑P0‑012：Demo UI 2.0 前端契约修复（/api/v1 + 稳定轮询 + 多图上传）

**为什么**：前端要尽量简单，所有功能尽可能交由后端；但 Demo 2.0 需要先把“能跑通且不崩”的基础设施修好，避免因路径/轮询/同步分支导致联调误判。

**执行计划入口（唯一）**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑A：A‑7.1‑FE）。

**状态**：✅ 已完成（/api/v1 对齐、强制异步、稳健轮询、多图上传打通；周报页白屏的 Hooks 竞态已修复）

**交付物**：
- 路径对齐：前端统一调用 `/api/v1/...`，Vite proxy 透传 `/api/v1`（无 rewrite）
- Robust Polling：停止条件为 `(done/failed) AND (无 review_pending 卡)`，并设置最大等待上限
- `/grade` 分支统一：推荐固定 `X-Force-Async: 1`，确保始终拿到 `job_id`
- 多图上传真正生效：`input[multiple]` + `onUpload(files[])` + `FormData.append('file', f)` 循环
- Dev 用户注入：如需 `X-User-Id` 兜底，改为 dev 环境变量控制（例如 `VITE_DEV_USER_ID`），避免硬编码进前端代码

**验收标准**：
- 任意一次上传→grade 都能进入同一套 “job_id + /jobs/{job_id} 轮询” 流程（避免 sync done 无 job_id 崩溃）
- `review_pending→review_ready/failed` 能在 UI 上稳定观察到（done 不会提前停轮询）
- 多图上传时后端返回 `pages(uploaded)=N`，并能逐页产出摘要与卡片

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

**实施方案（Design Doc）**：`docs/archive/design/mistakes_reports_learning_analyst_design.md`

**交付物**：
- 数据表（建议）：
  - `report_jobs`：异步任务（queued/running/done/failed；兼容 pending）
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

---

#### WL‑P1‑011：Report 解锁 Eligibility 接口（产品/演示口径统一）

**为什么**：前端“Report 解锁”不能通过 `/mistakes` 推断（全对 submission 会被漏掉）。需要后端提供权威统计口径，前端只负责展示进度条/禁用态，避免口径漂移与误伤“全对用户”。

**执行计划入口（唯一）**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑C：C‑4）。

**状态**：✅ 已实现（`GET /api/v1/reports/eligibility`）。

**交付物**：
- 新增接口：`GET /api/v1/reports/eligibility?subject=math&min_distinct_days=3&min_submissions=3`
- 返回结构（示例）：
  - `eligible`（bool）
  - `current_submissions/current_distinct_days`（int）
  - `required_submissions/required_distinct_days`（int）
  - `reason`（string，例：`need_more_days`）
- 数据源：优先 `submissions`（按 `created_at+subject+user_id` 聚合），避免依赖 `mistakes`

**验收标准**：
- Demo：同科目 ≥3 次 submission 立即解锁（不看对错）
- 产品：同科目 ≥3 天且满足最小 submissions/attempts 才解锁（阈值可配置）

---

#### WL‑P1‑012：报告趋势（知识点 Top5 + 错因 Top3，自适应 3 天分桶）

**为什么**：Reporter 详情页需要“趋势图”展示本周期内的变化；仅有整体聚合会缺失“相对变化”信息，且 30 天周期会出现点数爆炸/曲线噪声。

**唯一执行计划入口**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑C：C‑7）。

**交付物**：
- 在 reports 的 features/stats 中新增 `trends` 字段（稳定 schema）：
  - `granularity=submission|bucket_3d`
  - `points[]`（按时间升序，包含 `knowledge_top5` 与 `cause_top3` 的“绝对错题数”）
  - `selected_knowledge_tags[]` / `selected_causes[]`（用于前端图例）
- 防爆规则：
  - `distinct_submission_count <= 15` → 每次作业一个点
  - `> 15` → 按 UTC 日期 3 天游标分桶求和
- 口径要求：
  - 错题绝对数 = `verdict in {'incorrect','uncertain'}` 的题目数
  - 错因优先用题目级 `attempts.severity`（calculation/concept/format/unknown；**只统计错/待定题目**）
  - 必须与 `mistake_exclusions` 过滤口径一致

**验收标准**：
- 3/7 天周期：趋势点数=作业次数（≤15）；Top5/Top3 图例稳定，曲线不乱序、不缺点。
- 30 天周期：趋势点数≈ `ceil(days/3)`；`granularity='bucket_3d'`；bucket 求和可解释、可追溯。

---

#### WL‑P1‑013：Reporter 详情页数据契约补齐（KPI/薄弱点/错因口径/矩阵/覆盖率）

**为什么**：Reporter UI 需要“能画、能解释、能审计”的稳定字段；前端不应自行计数或推断口径（会导致 drift）。

**唯一执行计划入口**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑C：C‑8/C‑9）。

**交付物**：
- `reports.stats` 增加：
  - `coverage`（tag_coverage_rate / severity_coverage_rate / steps_coverage_rate）
  - `cause_distribution`（题目级 `attempts.severity` 聚合的 counts/rates）
  - `meta.cause_definitions`（severity → 中文名/判断标准，供 UI “!” tooltip）
- 保持现有：
  - `overall`（KPI）
  - `knowledge_mastery.rows`（薄弱知识点）
  - `type_difficulty.rows`（题型×难度）
  - `process_diagnosis`（steps 口径，允许稀疏但必须可解释）

**验收标准**：
- 前端仅用 `GET /api/v1/reports/{id}` 返回的 `reports.stats` 即可渲染 KPI/薄弱点/错因/矩阵/提示文案，无需二次计数。

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

#### WL‑P1‑006：多页作业“逐页可用”展示 + 可选进入辅导（方案 A：单 job + partial 输出）

**为什么**：多页作业若必须等全量结束才出结果，用户会“干等”；我们要做可持续运营闭环（作业→错题→辅导→复盘→报告），因此需要把批改过程变成“逐页可用”，并允许用户对已完成页先进入辅导，而不影响后台继续处理后续页。

**执行计划入口（唯一）**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑A：A‑6）。

**状态**：✅ 已实现（2026‑01‑02；实现位置：`homework_agent/workers/grade_worker.py`, `homework_agent/demo_ui.py`, `homework_agent/api/_chat_stages.py`, `homework_agent/services/llm.py`）

**前端用户感受（Demo UI 2.0）**：
- 上传 N 张图后立刻出现 N 个页卡（第 1/N…N/N）。
- 第 1 页先出摘要（错题数/待确认/needs_review），不等后续页。
- 每页卡片有“进入辅导（本页）”按钮（可选，不强制）。
- 全部完成后显示“本次 submission 汇总”与“生成学业报告”入口。

**后端交付物（最小契约）**：
- `/jobs/{job_id}` 在 `running` 时返回（除现有字段外）：
  - `total_pages`、`done_pages`
  - `page_summaries[]`：按页递增的摘要（`page_index, wrong_count, uncertain_count, needs_review, warnings(optional)`）
- `qbank:{session_id}` / `GET /session/{session_id}/qbank`：
  - `meta.pages_total/pages_done`（用于 UI 与 chat 边界提示）
  - 已完成页的证据链可被 chat 消费（保证“只基于已完成页回答”可实现）

**验收标准**：
- UI：第 1 页完成后 1 次 polling 内可见该页摘要；X/N 时显示进度，不会“全黑屏等待”。
- Chat：X/N 时提问，回复必须标注“仅基于已完成页（1..X）”，且不得引用未完成页内容。
- 成本/稳定性：并发（grade + chat）不应显著提高失败率；若 provider 限流，需要有可见提示与降级策略。

---

#### WL‑P1‑007：三层渐进披露（Question Cards：占位→判定→复核）

**为什么**：把“等待批改”从黑盒等待变成秒级可见、逐步变清晰、可中途交互的过程；支撑前端“占位卡刷出 + 翻转动画 + 追更模式”，显著降低用户焦虑。

**设计对齐文档**：`docs/design_progressive_disclosure_question_cards.md`

**状态**：✅ 后端已实现（2026‑01‑03；占位→判定→复核卡均已落地；实现位置：`homework_agent/workers/grade_worker.py`, `homework_agent/workers/review_cards_worker.py`, `homework_agent/services/grade_queue.py`, `homework_agent/services/review_cards_queue.py`, `homework_agent/services/autonomous_tools.py`, `homework_agent/core/question_cards.py`, `homework_agent/core/review_cards_policy.py`）

**当前执行优先级说明**：
- 近期验收以 **WL‑P0‑009（Layer 3 复核卡）** 为先（前端阻塞项）。
- Layer 1/2（占位/判定卡）后端已具备，前端可先隐藏/不强调，避免把 Demo 交互复杂度拉高；后续需要“翻转/追更”动效时再启用即可。

**后端交付物（最小契约）**：
- `/jobs/{job_id}` 在 `status=running` 时新增 `question_cards[]`（轻量列表，支持局部更新，不闪屏）：
  - `item_id`（string, stable key）
  - `question_number`（string）
  - `page_index`（int, 0-based）
  - `answer_state`（`blank|has_answer|unknown`）
  - `question_content`（可选但强烈建议：题干前 10–20 字）
- 空题口径：用 `answer_state=blank` 表达客观事实；不再使用“无法确认原因”误导用户；不做“不会/遗忘”等动机归因。
- 时间展示口径：前端以 `elapsed_ms/page_elapsed_ms` 展示（避免后台 Tab 降频导致 wall time 虚高）。

**前端交付物（Demo/产品通用）**：
- 以 `item_id` 作为列表 key，卡片可从占位态平滑翻转为判定态（局部更新不闪屏）
- 按 `page_index` 分组动效；允许部分完成即可进入辅导
- 空题渲染为灰色虚线卡片（中性提示文案）

**验收标准**：
- 上传完成后 ≤ 1 次 polling 内出现占位卡列表（非空）
- 每页完成后 ≤ 1 次 polling 内，该页卡片批量翻转为 verdict（或补全判定字段）
- 时间展示不再出现“后台挂起导致 700s”的误导（使用后端 elapsed）

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

### P2（上线前必须做｜不阻塞当前迭代）：部署与扩缩容（VKE/K8s）

#### WL‑P2‑001：VKE/K8s 生产化部署（5 组件拆分 + 按需扩缩容方案落地）

**为什么**：A‑4 已证明峰值下瓶颈主要来自 `grade_worker` 并发不足导致排队；上线前必须把系统拆成 `api + workers` 并支持“按需扩容 + 不中断升级 + 不丢任务”。

**唯一执行计划入口**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑D）。

**交付物**（建议落到 infra 仓库或 `deploy/` 目录）：
- 5 个 Deployment：`api / grade_worker / review_cards_worker / facts_worker / report_worker`
- HPA：`api`（CPU/内存/并发）
- KEDA：`grade_worker`（Redis 队列深度驱动扩缩容）
- 节点扩容：NodePool autoscaler 或 VCI/Serverless 节点（用于突发峰值）
- Secret/ConfigMap 规范：ARK keys、SUPABASE service role key 仅在运行环境；CI 继续做防泄露门禁
- 生产化最小代码补齐（不改业务逻辑）：API `/healthz`+`/readyz`、worker SIGTERM 优雅退出、启动时必需 env 自检（见 WS‑D D‑1/D‑5）

**已确认的关键决策（作为 WL‑P2‑001 的前置约束）**：
- 承载：**ECS 常驻 + VCI 承接 burst**（稳态成本可控，峰值快速扩）
- `grade_worker`：`max_inflight_per_pod=1`（先稳，靠扩 Pod 数承接峰值）

**验收标准**：
- `grade_worker` 可从 0 自动扩到 N（队列积压触发），队列清空后缩回
- 滚动升级不中断/可恢复（worker SIGTERM 优雅退出，避免丢任务）
- 429/限流/排队/失败可观测（能定位“模型侧 vs 存储侧 vs 本地”）

---

### P2（上线前必须做｜不阻塞当前迭代）：计费与配额（BT/CP/报告券）

#### WL‑P2‑003：用户系统与认证（H5 优先：强制手机号；火山短信；微信/抖音可选）

**为什么**：你已明确“首发 H5（手机浏览器）+ 强制手机号”，并且 WS‑E 的 BT/CP/报告券需要以真实 `user_id` 为真源；否则无法做付费产品、数据留存与权限隔离。

**唯一执行计划入口**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑F）。

**交付物**：
- 手机号验证码登录：
  - `POST /api/v1/auth/sms/send`
  - `POST /api/v1/auth/sms/verify`（返回 `access_token`）
- 用户与权限：
  - `GET /api/v1/me`
  - `Authorization: Bearer <token>` 作为生产唯一身份来源
  - `APP_ENV=prod` 禁用 `X-User-Id` DEV 兜底（避免误上生产）
- 与 WS‑E 对齐：
  - 注册即发放 Trial Pack（5 天）：`200 CP + 1 报告券 + bt_report_reserve`
  - `GET /api/v1/me/quota` 返回 `cp_left/report_coupons_left/trial_expires_at`
- 风控底线：
  - phone/ip/device 三层频控（防撞库/刷短信）
  - 验证码只存 hash，过期 5–10 分钟

**验收标准**：
- H5：手机号登录后能正常调用 `/uploads /grade /chat /mistakes /reports`，且数据按 `user_id` 隔离。
- Trial Pack 不会被 grade/chat 消耗掉“报告 BT 预留”（仍可用掉那张报告券）。

#### WL‑P2‑005：家庭-子女（Profile）账户切换（数据隔离 + 强提示 + 可补救）

**为什么**：同一家庭常见多子女共享设备；如果仍以 `user_id` 单维度存储，历史记录/错题/报告会混在一起，UI 切换只能“视觉切换”而无法做到数据隔离；且当用户忘记切换账号时，必须提供可补救的纠错机制。

**真源与契约**：
- 方案与分期：`docs/profile_management_plan.md`
- 前端真源补充：`docs/frontend_design_spec_v2.md`（§1.7）
- 契约草案：`homework_agent/API_CONTRACT.md`（Profiles Draft）

**唯一执行计划入口**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑F：F‑5）。

**交付物（后端/DB/Worker）**：
- DB：
  - 新增 `child_profiles` 表（同一 `user_id` 下 `display_name` 唯一；存在默认 profile）
  - 事实表新增 `profile_id`：`submissions/qindex_slices/question_attempts/question_steps/mistake_exclusions/report_jobs/reports`
  - 历史数据 backfill：所有用户至少 1 个默认 profile；旧数据回填到默认 profile
- API：
  - `GET/POST/PATCH/DELETE /api/v1/me/profiles`
  - `POST /api/v1/me/profiles/{profile_id}/set_default`
  - `POST /api/v1/submissions/{submission_id}/move_profile`（把 submission 及其派生事实迁移到另一 profile）
  - 全站读取接口按 `(user_id, profile_id)` 过滤；写入接口写入 `profile_id`
- Worker：
  - `profile_id` 以 `submissions.profile_id` 为事实源贯穿：upload/grade/qindex/facts/report 全链路写入与过滤

**交付物（前端）**：
- Home 右上角头像切换：profiles=2 时两个头像按钮并排，当前高亮（醒目、一眼可见）
- 全局请求头注入 `X-Profile-Id`（有 active_profile_id 时）
- 关键流程强提示：拍照/上传/开始批改处显示 `提交到：<profile>`；结果/历史详情显示 `归属：<profile>`
- 可补救入口：历史作业详情或汇总页提供“移动到其他孩子”

**验收标准**：
- 2 个 profile 下：切换后 History/DATA/Reports 均严格隔离；新上传/批改写入当前 profile
- 用户忘记切换后：可通过 move submission 纠正，且 UI 有明确提示与入口
- 兼容旧客户端：无 `X-Profile-Id` 也能跑通（自动使用默认 profile），但 UI 版本应始终携带 header

#### WL‑P2‑004：运营后台（Admin）与客服/审计（最小可用）

**为什么**：你已经进入“付费 + 数据留存 + 配额/报告券”的运营阶段；没有 Admin 与审计，就无法做客服排障、权益纠错、反作弊与成本治理（也无法解释“为什么扣费/为什么封禁/为什么报告不可用”）。

**唯一执行计划入口**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑G）。

**交付物（先最小可用，不追求 UI 漂亮）**：
- Admin 权限与鉴权：
  - `admin_users`（白名单）+ `Authorization` 仅 admin 可访问 `/api/v1/admin/*`
- 权益/客服操作（必须幂等 + 审计）：
  - `POST /api/v1/admin/users/{user_id}/grant`（发放/回收 CP/BT、报告券、延长试用/订阅）
  - `GET /api/v1/admin/users/{user_id}` + `GET /api/v1/admin/users/{user_id}/ledger`
- 作业/报告排障只读：
  - `GET /api/v1/admin/submissions?user_id=...`
  - `GET /api/v1/admin/submissions/{submission_id}` / `GET /api/v1/admin/jobs/{job_id}` / `GET /api/v1/admin/reports/{report_id}`
- 成本/用量最小报表（按天聚合）：
  - `GET /api/v1/admin/usage/daily?since=...`
  - `GET /api/v1/admin/usage/top_users?since=...`
- 审计日志（必做）：
  - `admin_audit_logs`：记录所有 admin 写操作（actor/action/target/payload/request_id/ip/ua）

**验收标准**：
- 任意一次 admin 写操作都有审计日志可追溯（可用于纠纷/风控）。
- 能用 Admin 在 5 分钟内定位并处理：用户“额度异常/报告券不可用/历史作业无法查看/报告失败”等典型客服问题。

#### WL‑P2‑002：BT 精确扣费 + CP 整数展示（含报告券/预留）

**为什么**：该产品为付费产品，成本主要来自 tokens；必须做到“严格按 tokens 扣费、可审计、可控成本”，并对用户只展示简洁的剩余额度。

**真源**：`docs/pricing_and_quota_strategy.md`（BT/CP 口径、Trial Pack、订阅等级、报告券与预留规则）。

**交付物**：
- 统一 usage 口径：所有 LLM 调用都产出结构化 usage（至少 `prompt_tokens/completion_tokens/total_tokens`）
  - 覆盖：`grade/chat/report`（包含 `LLMService.generate_report` 路径）
- 账户权益与账本（建议一个表/一组字段）：
  - `bt_trial`、`bt_subscription`
  - `trial_expires_at`
  - `report_coupons`、`bt_report_reserve`
  - `plan_tier`、`data_retention_tier`
- 扣费与幂等：
  - 以 `X-Idempotency-Key` 保护扣费（重试不重复扣）
  - `BT = prompt_tokens + 10 * completion_tokens`（严格按真源口径）
  - 扣费顺序：`grade/chat` 只扣 `trial/subscription`；`report` 先扣券、再扣 `bt_report_reserve`
- 对外查询（前端只需要剩余量）：
  - `GET /api/v1/me/quota` → `{ cp_left, report_coupons_left, trial_expires_at? }`
  - `cp_left = floor(bt_spendable / 12400)`（只展示整数 CP）

**验收标准**：
- 同一请求重复发送（相同 idempotency-key）不会重复扣费
- 当 `cp_left == 0` 但仍有 `report_coupons_left > 0` 时，周期报告仍可正常生成（使用 `bt_report_reserve`）
- 任意一次扣费都有审计记录：`request_id/user_id/endpoint/model/stage/prompt_tokens/completion_tokens/bt_used`

### P2（1–2 月）：规模化工程（灰度/告警/平台监控/Reviewer 工具）

只在确有上线与规模需求时再推进：
- Canary/Feature flags/AB
- 平台化监控（OTel/Prometheus/Grafana/Jaeger）与告警
- 安全响应演练 + postmortem 机制
- Reviewer UI/工作台（聚合 needs_review、回放轨迹、标注回收进 replay）

---

## P3（上线后第 1 个运营迭代）：支付/订阅自动化（最小版）

#### WL‑P3‑001：订阅生命周期状态机 + 自动结算（不绑支付渠道，Admin 可兜底）

**为什么**：你已确定“付费 + 数据留存 + BT/CP + 报告券”是产品核心；但首发可以先不接具体支付渠道。上线后需要在 1 个迭代内把“订阅内核”做成可审计、可回滚、可运营的状态机，否则运营会完全依赖人工、风险大且难规模化。

**唯一执行计划入口**：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS‑H）。

**交付物**（最小可用）：
- 订阅数据模型：`subscriptions`（status/plan_tier/period/cancel_at_period_end/provider_ref…）
- 订阅事件流水：`subscription_events`（幂等键=period/action；可追溯）
- 用户侧 API：
  - `GET /api/v1/me/subscription`
  - `POST /api/v1/me/subscription/cancel`
- Admin 侧 API（审计必做）：
  - `POST /api/v1/admin/subscriptions/activate|extend|revoke`
- 自动结算（不新增常驻服务）：
  - K8s CronJob（或等价定时任务）每日跑：到期回退 + 月度权益发放（幂等可重跑）

**验收标准**：
- 不接支付渠道也能完成：开通→续费（人工）→到期→宽限→过期回退；全程可观测、可审计。
- 订阅状态变化不会影响 WS‑E 扣费口径（BT/CP/报告券）与 WS‑A/WS‑C 的业务稳定性。

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
