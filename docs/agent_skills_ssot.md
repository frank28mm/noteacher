# Agent Skills（业务 Agent）唯一真源（SSOT）

> 本文档是“作业检查大师”中 **业务型 Agent Skills** 的唯一真源文件：定义 skills 的目的、目录结构、命名规范、加载方式、版本/灰度、观测与验收标准。  
> 注意：本文讨论的是 **运行在后端应用/worker 链路里的 skills**（面向业务 Agent 的能力包），不是“给开发/联调/IDE 用的 skills”。

---

## 0. 背景与现状（以代码为准）

系统现有关键链路与模块（仅列与 skills 直接相关部分）：

- /grade：`homework_agent/api/grade.py` → `perform_grading()` → 统一走 `homework_agent/services/autonomous_agent.py:run_autonomous_grade_agent()`
- 异步批改：`homework_agent/workers/grade_worker.py`（调用同一 `perform_grading()`）→ 落库 `submissions.grade_result`（快照）
- 事实抽取：`homework_agent/workers/facts_worker.py` → `homework_agent/services/facts_extractor.py:extract_facts_from_grade_result()`（当前主要为确定性规则）
- 报告生成：`homework_agent/workers/report_worker.py` → `compute_report_features()` +（可选）`homework_agent/prompts/report_analyst.yaml` 叙事层
- 题目定位/切片：`homework_agent/workers/qindex_worker.py` + prompt 在 `homework_agent/services/qindex_locator_siliconflow.py`、`homework_agent/services/ocr_siliconflow.py`
- 辅导聊天：`homework_agent/services/llm.py` 流式 tutor，system prompt 由 `homework_agent/prompts/socratic_tutor_system.yaml`（`PromptManager.render()`）加载

现有 prompt 管理能力：
- `homework_agent/utils/prompt_manager.py`：支持 YAML + variant（`foo.yaml` / `foo__B.yaml`）
- `homework_agent/prompts/*.yaml`：已存在 `math_grader_system.yaml` / `english_grader_system.yaml` / `report_analyst.yaml` / `socratic_tutor_system.yaml`
- Autonomous 多 Agent（Planner/Reflector/Aggregator）：当前 hardcode 在 `homework_agent/core/prompts_autonomous.py`

---

## 1. 目标（为什么要做“业务型 skills”）

业务型 skills 的目标不是“把 prompt 放到文件里”，而是把 **业务能力** 变成可控的能力包：

1) **可演进**：评分/归因/报告叙事/题目定位策略会频繁迭代，要求版本化、灰度、可回滚。  
2) **可观测**：每次批改/报告/辅导必须能回溯“用了哪些规则/模板/版本”。  
3) **可扩展**：新增学科/年级/地区规则时，不应靠复制粘贴代码，而应新增或覆盖 skill。  
4) **可协作**：工程与教研可以在同一“能力载体”上协作（工程保留 guardrails 与验收门禁）。  

非目标（明确不做/不在本文范围）：
- 不讨论 IDE/Codex/Claude Code 的开发者技能市场与插件安装（那是开发效率工具，不是线上业务能力）。
- 不在本文里设计新的产品功能或 UI，只定义后端/worker 的业务能力组织方式。

---

## 2. Skill 的定义（本项目口径）

本项目中，一个 skill 的定义：

- **Skill = 可加载的能力包目录**，最小包含 `SKILL.md`，可选包含 `scripts/`、`references/`、`assets/`。
- skill 的“核心价值”是：为某个业务阶段（stage）提供 **稳定、可复用、可版本化** 的策略/规则/模板/约束。

### 2.1 渐进式披露（Progressive disclosure）

遵循 Agent Skills 通用规范（agentskills.io/Claude Docs/Codex Docs 共同强调）：

- Level 1：元信息（总是加载）  
  - `name` / `description` / `metadata.version` 等，**常驻上下文应尽量短**。
- Level 2：正文指令（按需加载）  
  - `SKILL.md` 正文（建议控制在可读、可审计的规模；避免把长篇资料塞正文）。
- Level 3：资源（按需加载）  
  - `references/`（长文规则/字典/示例库）、`assets/`（模板/Schema/Prompt YAML）、`scripts/`（确定性校验与转换）。

---

## 3. 目录结构（线稿/可视化）

### 3.1 推荐目录树

建议将业务型 skills 以代码库内目录作为真源（便于 review、版本控制、灰度）：

```text
homework_agent/agent_skills/
  autonomous/
    planner/
      SKILL.md
      assets/
        planner_system_prompt.md
      references/
        tool_selection_rules.md
    reflector/
      SKILL.md
      assets/
        reflector_system_prompt.md
    aggregator_math/
      SKILL.md
      assets/
        aggregator_system_prompt_math.md
    aggregator_english/
      SKILL.md
      assets/
        aggregator_system_prompt_english.md

  grading/
    math_grader_system/
      SKILL.md
      assets/
        prompt.yaml            # 等价于现有 homework_agent/prompts/math_grader_system.yaml
      references/
        knowledge_tags_policy.md
    english_grader_system/
      SKILL.md
      assets/
        prompt.yaml

  tutoring/
    socratic_tutor/
      SKILL.md
      assets/
        prompt.yaml            # 等价于现有 homework_agent/prompts/socratic_tutor_system.yaml
      references/
        latex_policy.md

  reporting/
    report_analyst/
      SKILL.md
      assets/
        prompt.yaml            # system_template/user_template + schema 约束
      references/
        narrative_style_guide.md

  qindex/
    locator_v2/
      SKILL.md
      assets/
        locator_prompt.md       # 对应 qindex_locator_siliconflow.py:_prompt()
      references/
        question_number_formats.md
    ocr_locator_v1/
      SKILL.md
      assets/
        ocr_locator_prompt.md   # 对应 ocr_siliconflow.py:_prompt()

  extraction/
    facts_rules_v1/
      SKILL.md
      references/
        severity_mapping.md
      scripts/
        normalize_tags.py
```

> 说明：上面目录只是 SSOT 目标形态（便于版本化与灰度）。落地可以先“镜像现有 YAML 与 hardcode prompt”，再逐步迁移代码引用点。

### 3.2 链路视图（业务阶段与 skills）

```text
           ┌───────────────────────────┐
           │ /api/v1/grade (API)       │
           └─────────────┬─────────────┘
                         │
                         ▼
                 perform_grading()
                         │
                         ▼
          run_autonomous_grade_agent()  ← autonomous/* skills
          (Planner → Tools → Reflector → Aggregator)
                         │
                         ▼
                submissions.grade_result (snapshot)
                         │
         ┌───────────────┼────────────────┐
         ▼               ▼                ▼
  facts_worker       qindex_worker     chat/report
  extraction/*       qindex/*          tutoring/*, reporting/*
```

---

## 4. Skills 分类（以现有代码模块为基准）

> 本节定义“哪些能力应该 skill 化”，并对齐到现有文件。

### 4.1 Autonomous（Planner / Reflector / Aggregator）

对应代码：
- hardcode prompt：`homework_agent/core/prompts_autonomous.py`
- runtime：`homework_agent/services/autonomous_agent.py`

skill 化目标：
- 将 hardcode prompt 收敛为可版本化 assets（便于灰度、回滚、AB）
- 把“工具选择策略/证据门禁/输出 schema 约束”从代码剥离成可审计的能力包

### 4.2 Grading（学科评分系统）

对应代码：
- `homework_agent/prompts/math_grader_system.yaml`
- `homework_agent/prompts/english_grader_system.yaml`

skill 化目标：
- prompt 从“单文件”升级为“能力包”：规则（references）+ 输出 schema（assets）+ 版本（frontmatter）
- 支持变体：年级/地区/考试体系差异 → 通过 variant 或多个 skill 并存实现

### 4.3 Tutoring（辅导）

对应代码：
- `homework_agent/prompts/socratic_tutor_system.yaml`
- runtime：`homework_agent/services/llm.py`（已支持 prompt variant）

skill 化目标：
- 强化“苏格拉底策略/长度约束/公式规范/视觉事实引用策略”的一致性与版本化

### 4.4 Reporting（报告叙事）

对应代码：
- `homework_agent/prompts/report_analyst.yaml`
- runtime：`homework_agent/workers/report_worker.py`（当前直接 `_load` 并取 `system_template/user_template`）

skill 化目标：
- 报告叙事结构（标题/段落/行动建议）与输出 schema 固化
- 让“叙事层”可灰度：例如 report_narrative_enabled + skill version

### 4.5 QIndex（题目定位/切片）

对应代码：
- `homework_agent/services/qindex_locator_siliconflow.py:_prompt()`（v2：question+figure regions）
- `homework_agent/services/ocr_siliconflow.py:_prompt()`（v1：仅 question bbox）
- runtime：`homework_agent/workers/qindex_worker.py`（调用 `build_question_index_for_pages`）

skill 化目标：
- 将题号格式、bbox规范、figure 强制策略、排序规则等抽为可版本化能力
- 便于你们后续“按需触发 qindex”的策略演进（减少对链路时延的影响）

### 4.6 Extraction（事实抽取/归因）

对应代码：
- `homework_agent/services/facts_extractor.py`（当前为确定性规则；已有 `severity` best-effort 推断）
- `homework_agent/workers/facts_worker.py`（写入 `question_attempts/question_steps`）

skill 化目标：
- 规则与字典可维护：severity/diagnosis codes/knowledge tag normalize
- 将“归因口径”与“前端展示口径”对齐（减少未分类/噪声 tag）

---

## 5. Skill 的“载荷类型”（你们应该封装什么）

一个业务型 skill 允许包含以下载荷（按需选）：

1) **Prompt assets**（推荐）  
   - YAML 模板（对齐现有 `PromptManager`）：`assets/prompt.yaml`
   - system/user template + schema 约束 + 输出示例

2) **规则与字典**（推荐）  
   - `references/*.md`：knowledge_tags 命名规范、错因定义、题型规则、题号格式、latex规范等

3) **确定性脚本**（慎用，但必要时很关键）  
   - `scripts/*.py`：只做确定性处理（规范化/校验/转换/打标签），不得引入不可控副作用

---

## 6. 加载与选择（运行时机制建议）

> 本节只定义“应该怎么做”，不要求立即改造到位。

### 6.1 Skill Registry（发现与元信息）

启动扫描：`homework_agent/agent_skills/**/SKILL.md`  
只解析 frontmatter，得到：
- `name`
- `description`
- `metadata.version`
- `metadata.stage`（建议新增）
- `metadata.owner`（建议新增：engineering/teaching-research）
- `compatibility`（是否依赖网络/某 provider）

### 6.2 Skill Router（由业务代码选择，不把选择权完全交给 LLM）

建议默认策略：
- 业务代码根据 stage/subject/provider/feature_flags 决定“激活哪些 skill”
- LLM 不做自由选择（避免漂移）；最多只对“归因/知识点映射”做受控选择

### 6.3 版本/灰度（必须）

每次运行必须落日志（建议扩展 `log_event(..., run_versions=...)`）：
- `skill_names[]`
- `skill_versions[]`
- `skill_hashes[]`（可对 SKILL.md + assets 做 stable hash）

支持灰度策略：
- 环境变量/feature flag 选择 skill variant（类似你们现在 `PromptManager` 的 `foo__B.yaml`）
- 回滚只改配置，不改代码

---

## 7. 验收与门禁（如何证明 skills “有用且不回归”）

每类 skill 给出最小验收标准（必须可自动化回放）：

- Autonomous（planner/reflector/aggregator）：  
  - 输出严格 JSON 不崩；tool 选择稳定；needs_review 率可控；错误可解释
- Grading（math/english）：  
  - 输出字段稳定（questions/wrong_items/knowledge_tags/judgment_basis）；空白题不误判；LaTeX 规范一致
- QIndex：  
  - bbox 归一化合法；figure 策略不丢；题号排序稳定；异常有 warnings
- Reporting：  
  - narrative 输出严格 JSON；覆盖度不足时能说明原因；不输出 markdown code block
- Tutoring：  
  - 回答长度受控；不一次性给答案；公式渲染规范；仅基于 submission 上下文

建议把验收样本接入你们已有测试框架：
- `homework_agent/tests/test_autonomous_*`
- replay_data（如未来补充）  

---

## 8. 落地路线（建议分两阶段）

阶段 1（最小迁移、快速建立真源）：
- 把现有 YAML prompts 镜像进对应 skill 的 `assets/`（不改业务逻辑）
- 把 `prompts_autonomous.py` 的三段 hardcode prompt 镜像进 skill assets
- 先只做“技能目录 + 元信息 + 版本号 + 运行时打点”

阶段 2（真正让 skill 成为运行时能力包）：
- 在关键入口（/grade、report_worker、qindex locator、tutor）把 prompt 加载从“固定路径”切换为“按 skill 选择 + variant”
- 引入 `references/` 的按需注入与脚本校验（例如 tag normalize、作答存在性 guard）

---

## 9. 维护规范（写 skill 的硬规则）

- `description` 必须写清楚触发条件（面向 Router/选择器），避免含糊导致选错
- 正文优先写：输入/输出/步骤/边界/失败策略/验收
- 长资料一律下沉到 `references/`
- 引用链不要深（从 `SKILL.md` 往下建议只引用一层文件）
- scripts 必须可审计、可复现、可观测（出错要可读），且不得执行危险操作

---

## 10. 附录：参考链接（规范来源）

- Agent Skills 规范：`https://agentskills.io/specification`
- 集成指南：`https://agentskills.io/integrate-skills`
- Codex Skills：`https://developers.openai.com/codex/skills/`
- Claude Skills 概览：`https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview`
- Claude Code Skills：`https://code.claude.com/docs/en/skills`
- Anthropic skills 示例库：`https://github.com/anthropics/skills`

---

## 11. 附录：参考实现（最小可行，伪代码级）

> 下面内容来自两份草稿方案中可复用部分，已按本项目口径改写（skills 真源目录：`homework_agent/agent_skills/`，由业务代码路由选择；并保留“找不到 skill 时 fallback 到现有 hardcode/YAML prompt”的策略）。

### 11.1 `SKILL.md` frontmatter 约定（建议）

建议使用 YAML frontmatter（`---`…`---`）存放元信息，正文放可加载指令：

```yaml
---
name: math_grader_system
description: Math grading system prompt (system+schema+guardrails)
metadata:
  stage: grading
  subject: math
  version: 1.0.0
  owner: engineering
compatibility:
  providers: [ark, siliconflow]
---
```

### 11.2 Skill Registry（发现 + 元信息）

目标：启动时扫描 `homework_agent/agent_skills/**/SKILL.md`，只解析 frontmatter，构建 registry。

```python
@dataclass
class SkillMetadata:
    name: str
    description: str
    path: Path
    version: str
    stage: str | None = None
    subject: str | None = None
    owner: str | None = None

class SkillRegistry:
    def __init__(self, skills_root: Path):
        self.skills_root = skills_root
        self.skills: dict[str, SkillMetadata] = {}
        self._discover()

    def _discover(self) -> None:
        for skill_md in self.skills_root.glob("**/SKILL.md"):
            meta = self._parse_frontmatter(skill_md)
            if meta:
                self.skills[meta.name] = meta

    def _parse_frontmatter(self, skill_md_file: Path) -> SkillMetadata | None:
        content = skill_md_file.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return None
        end = content.find("---", 3)
        if end == -1:
            return None
        frontmatter = yaml.safe_load(content[3:end].strip()) or {}
        if not frontmatter.get("name") or not frontmatter.get("description"):
            return None
        metadata = frontmatter.get("metadata", {}) or {}
        return SkillMetadata(
            name=frontmatter["name"],
            description=frontmatter["description"],
            path=skill_md_file.parent,
            version=metadata.get("version", "0.0.0"),
            stage=metadata.get("stage"),
            subject=metadata.get("subject"),
            owner=metadata.get("owner"),
        )
```

### 11.3 读取正文（按需加载）

目标：只在需要注入上下文时读取 `SKILL.md` 正文，避免常驻上下文膨胀。

```python
def read_skill_body(skill_md_file: Path) -> str:
    content = skill_md_file.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return content
    end = content.find("---", 3)
    if end == -1:
        return content
    body_start = end + 3
    while body_start < len(content) and content[body_start] in "\n\r":
        body_start += 1
    return content[body_start:]
```

### 11.4 业务路由选择（强约束，非 LLM 自选）

目标：由业务代码根据 stage/subject/flags 明确选 skill（或 variant），找不到时 fallback。

```python
class SkillRouter:
    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def select(self, *, stage: str, subject: str | None, variant: str | None) -> str | None:
        # 兼容层：先用显式映射（可从配置加载），避免“语义匹配漂移”
        mapping = {
            ("grading", "math"): "math_grader_system",
            ("grading", "english"): "english_grader_system",
            ("tutoring", None): "socratic_tutor",
            ("reporting", None): "report_analyst",
        }
        name = mapping.get((stage, subject))
        if not name:
            return None
        if variant:
            # 例：name__B / name__strict（保持与 PromptManager 的 variant 习惯一致）
            candidate = f"{name}__{variant}"
            if candidate in self.registry.skills:
                return candidate
        return name if name in self.registry.skills else None
```

fallback（必须保留）：
- autonomous：找不到 skill → 用 `homework_agent/core/prompts_autonomous.py`
- grading/tutor/report：找不到 skill → 用 `homework_agent/prompts/*.yaml`（或现有 `PromptManager`）

### 11.5 可选：调试端点（仅内网/开发态）

如果需要排障“线上到底加载了哪个 skill/版本”，可以提供只读端点（不必暴露正文）：
- `GET /api/v1/skills`：列出 `name/description/version/stage/subject/hash`
- `GET /api/v1/skills/{name}`：列出 metadata + assets 清单（不直接返回 references）

---

## 12. 附录：实施检查清单（参考）

> 下面是实施顺序建议，不作为排期承诺；用于团队对齐“先做什么、后做什么”。

### Phase 1：建立真源与可观测（最优先）
- [ ] 创建 `homework_agent/agent_skills/` 目录树（先镜像现有 prompts）
- [ ] 为每个 skill 补齐 frontmatter：`name/description/metadata.stage/metadata.version`
- [ ] 实现最小 `SkillRegistry` + hash 计算，并在关键链路 `log_event` 打点记录（skill/version/hash）

### Phase 2：接入路由选择（只改加载点，不改业务逻辑）
- [ ] grading：从固定 `prompts/*.yaml` 改为“router 选 skill → 读 assets/prompt.yaml”
- [ ] tutoring：同上（保持 `PromptManager` variant 兼容）
- [ ] reporting：同上（report_analyst 的 system/user template + schema 固化）

### Phase 3：Autonomous hardcode prompt 解耦
- [ ] 将 `prompts_autonomous.py` 迁移为 `autonomous/*` skills 的 assets（保留 fallback）
- [ ] 引入 feature flag 灰度切换（skill 版 vs hardcode 版）

### Phase 4：把 references/scripts 纳入门禁
- [ ] 引入 “知识点/错因/latex 规范” references 的按需注入策略
- [ ] 引入 scripts（只做确定性校验与规范化）并补齐单测与可观测
