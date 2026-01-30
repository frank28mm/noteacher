# Frontend Design Specification (NoTeacher UIUX, v2.3)
**Frontend Source of Truth (H5-first, Mobile-first)**
**Last Updated**: 2026-01-11

此文档是前端实现的**唯一真源**，以 `noteacher-UIUX.excalidraw`（最新 UI/流程示意图）为主依据，并与当前后端能力做了可落地对齐。任何**页面命名/按钮文案/跳转规则**的变更，必须先更新本文件再实现。

## 0) Sources

- UI/Flow truth: `noteacher-UIUX.excalidraw`
- Backend API base: `/api/v1/*`

---

## 1) Unified Naming (must match UI)

### 1.1 Home entry buttons（主页内入口按钮，非底部 Tab）

- `批改历史记录` (HISTORY)
- `数据档案` (DATA)
- `分析` (ANALYSIS)
- `我的` (MINE)
- `SCAN`（主页中央主入口）

### 1.2 Core pages

- `拍照页面`
- `照片预览/上传页面`
- `批改结果页面（逐页披露）`（占位卡/逐页进度）
- `批改结果页面（汇总/最终）`（全量完成后的最终汇总 UI；与逐页披露页不同）
- `题目详情（有图）` / `题目详情（无图）`
- `AI辅导`（整页跳转；不是 Drawer/Modal）

### 1.3 DATA（数据档案）panels（同构：结构一致、数据不同）

- `错题面板`（默认）
- `已掌握面板`
- `分类面板/列表页`（由“分类模块按钮”进入，展示题目列表）

### 1.4 ANALYSIS（分析）pages

- `分析页面`（内嵌筛选控件 + Start）
- `报告详情页`（Start 后直接进入）
- `报告记录列表`（从分析页面左下角入口进入）

### 1.5 HISTORY pages

- `批改历史记录列表`
- `历史作业详情页`
- `历史筛选弹窗`（存在；关闭即回列表）

### 1.7 家庭-子女（Profile）账户切换（数据隔离口径）

> 注意：这里的 **Profile=子女档案/子账号**（用于数据隔离与切换视图），不是“学生画像/知识画像”的那种 Profile。

#### 1.7.1 基本原则（v1 已确认）
- **家庭共用配额**：计费/配额归属 `user_id`（家长主账号），不按孩子计费。
- **数据隔离维度**：前端切换 Profile 后，全站列表/详情只展示该 `profile_id` 下的数据。
- **不做阻断式预防**：不做“每次上传前强制弹窗选择”；只做“强提示 + 可补救”。

#### 1.7.2 Home 页：头像切换 UI（醒目优先）
- profiles=1：右上角显示 1 个头像按钮（仅展示当前 Profile；点击可显示“当前：xxx”，无切换项、无登出项）。
- profiles=2：右上角并排显示 2 个头像按钮（当前 Profile 明显高亮：ring/轻动效/更深阴影），点任一头像立即切换。
- profiles>2：显示当前 + 次级头像 + “更多”入口（Popover 列表切换；具体样式可后续细化）。

#### 1.7.3 关键流程强提示（必须）
在以下关键动作附近，必须展示“当前提交到谁”，降低误传风险：
- `照片预览/上传页面`：上传按钮上方固定文案：`提交到：<profile_display_name>`（可点切换）。
- `拍照页面`：顶部或底部展示 `当前：<profile_display_name>`（可点切换）。
- 进入批改流程后：`批改结果页面（逐页披露）/（汇总/最终）` 顶部展示 `归属：<profile_display_name>`。

#### 1.7.4 可补救（必须）
- 在 `历史作业详情页` 或 `批改结果页面（汇总/最终）` 提供入口：`移动到其他孩子`（调用后端 move submission 接口）。
- UI 提示语：强调“移动后报告可能需要重新生成才会更新”（不阻断）。

#### 1.7.5 API 调用约定（前端必须做）
- 对所有 `/api/v1/*` 请求，若已选择 Profile，则在请求头注入 `X-Profile-Id`。
- 若本地没有 active_profile_id（例如首次登录/单 profile），不注入；由后端兜底到默认 profile。

---

### 1.8 订阅/升级订阅（首发：卡密兑换模式）

> 首发商业化采用「卡密兑换」实现订阅/升级：用户通过兑换码激活权益（BT/CP/报告券），不接入在线支付。
> 产品概念仍为「订阅/升级」，卡密只是支付方式的替代。

#### 1.8.1 页面入口
- 位置：`我的` 页面 → `订阅/升级` 按钮
- 导航规则：无 HOME 键，仅 Back（返回「我的」页面）

#### 1.8.2 页面结构
```
┌────────────────────────────────────────────┐
│ ← Back            订阅/升级                  │
├────────────────────────────────────────────┤
│                                            │
│  请输入兑换码                                │
│  ┌────────────────────────────────────┐   │
│  │  XXXX-XXXX-XXXX-XXXX               │   │
│  └────────────────────────────────────┘   │
│                                            │
│  ┌────────────────────────────────────┐   │
│  │           立即兑换                   │   │
│  └────────────────────────────────────┘   │
│                                            │
│  [兑换结果提示区域]                          │
│                                            │
└────────────────────────────────────────────┘
```

#### 1.8.3 交互规则
- **输入框**：单行文本，支持自动格式化（如 `XXXX-XXXX-XXXX`）
- **兑换按钮**：Primary CTA 样式（统一按 `START` 样式）
- **结果提示**：
  - 成功：绿色提示「兑换成功！已获得 X 次批改额度 + Y 张报告券」
  - 失败：红色提示「兑换码无效/已使用/已过期」
- **刷新配额**：兑换成功后自动刷新 `GET /api/v1/me/quota`

#### 1.8.4 API 契约
- 请求：`POST /api/v1/redeem`
  ```json
  { "code": "XXXX-XXXX-XXXX" }
  ```
- 响应（成功）：
  ```json
  { "success": true, "bt_added": 12400, "coupons_added": 1, "message": "兑换成功" }
  ```
- 响应（失败）：
  ```json
  { "success": false, "error": "invalid_code", "message": "兑换码无效" }
  ```

#### 1.8.5 文案规范（中英双语）
| 场景 | 中文 | English |
|------|------|---------|
| 页面标题 | 订阅/升级 | Subscribe / Upgrade |
| 输入提示 | 请输入兑换码 | Enter your redemption code |
| 按钮文案 | 立即兑换 | REDEEM |
| 成功提示 | 兑换成功！已获得 {n} 次批改额度 | Success! {n} grading credits added |
| 无效码 | 兑换码无效 | Invalid code |
| 已使用 | 该兑换码已被使用 | This code has already been used |
| 已过期 | 该兑换码已过期 | This code has expired |

---

## 1.6 Copy & Typography Rules（中英双语 + 文案/字体统一）

目标：在不牺牲“高度还原 `docs/frontend_ui_page_code.md` 单页效果”的前提下，把**文字体系**做成可复用、可维护、可扩展的统一规则。

### 1.6.1 中英双语（必须）

- 整个 UI 必须支持 **中文/英文** 两套文案。
- **严格不混用**：中文界面尽量全中文；英文界面全英文（不出现中英夹杂的按钮/标题）。
- 英文整体观感基准：优先参照 `数据档案/错题面板` 的英文视觉（`DATA ARCHIVE` 页面风格，`docs/frontend_ui_page_code.md:2041`）。

### 1.6.2 固定命名（底部导航与编号）

- 底部导航（中文）：`首页 / 历史 / 数据 / 分析 / 我的`
- Bottom nav (English)：`HOME / HISTORY / DATA / ANALYSIS / ME`
- 所有“对用户可见的编号”统一：**永远使用 `#` 前缀**（例如 `#84021`），适用于：
  - 批改历史记录条目编号
  - 报告记录条目编号
  - 作业详情页展示的作业编号

### 1.6.3 文字类别统一（以页面原型为锚点）

说明：下面每一类都指定了“参考锚点”。实现时要求**字体/字重/字号/颜色/字距**与锚点一致；文案内容则按本规范的页面命名与业务语义替换。

| 文字类别 | 统一规则（中文） | 统一规则（英文） | 参考锚点（`docs/frontend_ui_page_code.md`） |
|---|---|---|---|
| Page Title（页面主标题） | 采用 `历史记录` 的视觉样式（但文案按页面命名） | 采用 `Analysis` 的视觉样式 | `历史记录`：`docs/frontend_ui_page_code.md:2923`；`Analysis`：`docs/frontend_ui_page_code.md:2402` |
| Section Header（分区标题） | 统一按 `错因统计` 的 section title 样式 | 同一套样式 | `docs/frontend_ui_page_code.md:2577`（样式定义见 `docs/frontend_ui_page_code.md:2505`） |
| Subheader（子标题/辅助说明） | 统一按 `正确率` 的样式 | 同一套样式 | `docs/frontend_ui_page_code.md:2536` |
| Card Title（卡片标题） | 统一按 `代数` 的样式 | 统一按 `Algebra` 的样式 | `代数`：`docs/frontend_ui_page_code.md:2233`；`Algebra`：`docs/frontend_ui_page_code.md:2066` |
| Card Meta（卡片副标题/元信息） | 保持页面原型各自的 meta（不强行统一） | 同左 | 例如：历史记录 `#84021 · 14:30`（`docs/frontend_ui_page_code.md:2909`） |
| List Primary（列表项主文本） | 统一按历史列表 `数学/英语/物理` 的样式 | 同一套样式（英文时换成对应英文科目名） | `docs/frontend_ui_page_code.md:2897`、`docs/frontend_ui_page_code.md:2938` 等历史列表条目 |
| Metric Value（指标数值） | 统一按报告详情 `85%/50/12/1` 的数值样式 | 同一套样式 | `docs/frontend_ui_page_code.md:2535`、`:2540`、`:2545`、`:2550` |
| Primary CTA（主按钮） | 主按钮样式统一按 `START` | 同一套样式 | `docs/frontend_ui_page_code.md:2434` |
| Secondary CTA（次要按钮） | 统一按 `全部/待复习/已掌握` 的 segmented 样式 | 英文同义替换（All/To Review/Mastered） | `docs/frontend_ui_page_code.md:2238`、`:2241`、`:2244` |
| Tertiary/Icon Button（图标弱按钮） | 图标按钮统一按历史页 `tune` 的 header icon button | 同一套样式 | `docs/frontend_ui_page_code.md:2925` |
| Text Link（文本链接） | 文本链接统一按登录页协议链接样式 | 同一套样式 | `docs/frontend_ui_page_code.md:3807` |
| Input Placeholder（输入占位符） | 统一按 AI 辅导输入框 placeholder 样式 | 同一套样式 | `docs/frontend_ui_page_code.md:1955` |
| Helper Text（帮助/说明小字） | 统一按 `题目内容加载中...` 的弱文本样式 | 同一套样式 | `docs/frontend_ui_page_code.md:1029` |
| Status/Progress（状态/进度文案） | 统一按批改流程 `正在上传图片/正在识别题目.../等待分析` 的样式层级 | 同一套样式（英文替换） | `docs/frontend_ui_page_code.md:700`、`:873`、`:1047` |
| Tag（知识点/分类标签） | 统一按分类面板 tag 样式（如 `函数/最值`） | 英文同义替换 | `docs/frontend_ui_page_code.md:2260`、`:2261`、`:2299` |
| Badge（判定徽标） | 统一按 `Wrong/Correct` pill 样式（中文/英文替换） | 同一套样式 | `docs/frontend_ui_page_code.md:1401`、`:1453` |
| MathRichText（数学推导/步骤正文） | 数学长段落统一按 `text-[14px] text-text-gray leading-loose`，行内公式用 mono 高亮 | 同一套样式（英文替换） | `docs/frontend_ui_page_code.md:1596`、`:1749` |

### 1.6.4 空状态 / 处理中 / 错误 / 成功（统一文案）

这些文案用于列表为空、长任务仍在跑、真实失败等场景；与“轮询超时不等于失败”的体验原则一致（详见 §4.1）。

- Empty（空状态）
  - 中文：`暂无数据` / `完成一次批改后，这里会自动生成记录。`
  - English：`No data yet` / `Finish one grading to see results here.`
- Warning（仍在处理中，不是失败）
  - 中文：`仍在处理中` / `系统仍在批改，请继续等待。`
  - English：`Still processing` / `This job is still running. Please keep waiting.`
- Error（真实失败）
  - 中文：`出现问题` / `服务暂时不可用，请稍后重试。`
  - English：`Something went wrong` / `Please try again later.`
- Success（成功）
  - 中文：`已完成` / `结果已更新。`
  - English：`Done` / `Your results are updated.`

---

## 2) Navigation Rules（真实口径）

**不是所有页面都有 HOME 键。**

### 2.1 No HOME key pages（仅 Back / Close）

- `AI辅导`（整页，仅返回上一层）
- `登录/注册`
- `订阅/升级订阅`（首发通过卡密兑换实现）
- `历史筛选弹窗`（弹窗仅关闭）

### 2.2 HOME 返回时的主页状态（批改任务进行中）

当用户在**批改任务进行中**点击 HOME 返回主页时，主页必须进入“任务进行中”状态：

- 显示 `任务进行中` 状态卡（或底部/顶部进度条）：
  - 进度：`done_pages / total_pages`
  - 状态文案：`处理中` / `第 N 页已完成`
  - 保留一个明确入口：`继续查看`（跳转回 `批改结果页面（逐页披露）`）
- 当任务 **已完成但用户尚未查看汇总页**：
  - 首页显示 `已完成` 状态卡，并提供 `查看结果`（进入 `批改结果页面（汇总/最终）`）
- 当**无任务**时，主页恢复默认入口（SCAN + HISTORY/DATA/ANALYSIS/MINE）

说明：
- HOME 返回不应中断任务（后台仍继续处理）。
- 任务状态来源：`GET /api/v1/jobs/{job_id}`（若仅有 session_id，可由前端持久化最新 job_id）。

---

## 3) End-to-End Flows（业务链路）

### 3.1 Scan-to-Learn（智能批改主链路）

1. `主页` → 点击 `SCAN` → 进入 `拍照页面`
2. 拍照/选图 → 进入 `照片预览/上传页面`
3. 点击 `上传` 后，**自动进入批改流程**（没有“提交批改”第二按钮）：
   - 上传约束：一次最多 4 张；单张图片 ≤ 5MB（超限需提示用户重新选择/压缩后再传）。
   - `POST /api/v1/uploads`（多图 FormData）→ `upload_id / page_image_urls / total_pages`
   - **立即自动** `POST /api/v1/grade`（建议前端固定 `X-Force-Async: 1`）→ `job_id`
4. 自动进入 `批改结果页面（逐页披露）`，轮询 `GET /api/v1/jobs/{job_id}`
5. **逐页披露（按 Page）**
   - Page 1 先出：该页题目卡出现（正确/错误/待定）并可立即交互：
     - 点击题目卡 → `题目详情（有图/无图）`
     - 点击题目卡上的 `问问AI` → 进入 `AI辅导`（整页）
   - Page 2/3 后台继续：逐页补齐，页完成时该页卡片批量更新为最终判定
6. **全部页完成后（整单 done）**
   - 进入/切换到 `批改结果页面（汇总/最终）`（UI 与逐页披露页不同，展示最完整稳定的汇总结果）
   - 交互规则与逐页披露一致：
     - 点击题目 → `题目详情（有图/无图）`
     - 点击题目上的 `问问AI` → `AI辅导`（整页）
7. `AI辅导` 结束 → Back 返回上一层（题目详情/批改结果页）

### 3.2 HISTORY（批改历史记录）

1. `主页` → 点击 `批改历史记录` → 进入 `批改历史记录列表`
2. 列表单条目必须展示：
   - **批改编号**（每次批改独有编号；建议 `display_id/short_id`，避免把长 UUID 暴露给用户）
   - 时间/科目/页数/摘要（错题/待定/正确等）
3. 点击单条目 → `历史作业详情页`（快照回放，不重新批改）
4. `历史作业详情页`：
   - 可按页查看题目卡
   - 点击题目 → `题目详情（有图/无图）`
   - 题目卡或题目详情点击 `问问AI` → `AI辅导`
5. 点击筛选按钮 → `历史筛选弹窗`（关闭即回列表；弹窗无 HOME 键）

### 3.3 DATA（数据档案：错题/已掌握同构）

1. `主页` → 点击 `数据档案` → 进入 `错题面板`（默认）
2. `错题面板`展示多个**分类模块按钮**：
   - 点击分类模块按钮 → 进入对应 `分类面板/列表页`（错题题目列表）
3. `分类面板/列表页`（题目列表）：
   - 点击题目条目 → `题目详情（有图/无图）`
   - 点击 `OK` → **不可逆**归档 → 题目进入 `已掌握面板`
4. `数据档案`左下角 `OK 图标`：
   - 切换进入 `已掌握面板`
5. `已掌握面板`与 `错题面板`**结构完全一致（仅数据不同）**：
   - 也有分类模块按钮
   - 点击分类模块按钮 → 进入对应 “已掌握题目列表”
   - 点击题目条目 → `题目详情（有图/无图）`
   - 可继续 `问问AI` → `AI辅导`

### 3.4 ANALYSIS（分析：生成报告 → 详情 → 记录）

1. `主页` → 点击 `分析` → 进入 `分析页面`
2. `分析页面`内嵌筛选控件（无筛选弹窗）：
   - 科目（必选）
   - 周期（固定：3天/7天/30天）
3. 点击 `Start`：
   - 创建报告任务并**直接进入** `报告详情页`
4. 退出 `报告详情页` → 回到 `分析页面`
5. `分析页面`左下角点击 `报告记录` → `报告记录列表`
6. `报告记录列表`单条目必须展示：
   - **报告编号**（每次报告独有编号；建议 `display_id/short_id`）
   - 时间/科目/周期/摘要

---

## 4) Frontend Requirements (DoD / Acceptance)

### 4.1 Long-running jobs（轮询不得“卡死/误判失败”）

- **轮询超时不等于失败**：不得因为超过固定时长就进入错误页；仍应持续追更，直到后端 `job.status=done/failed`。
- **不新增“超时分支按钮”**：UI 始终保持同一条主流程（逐页披露 + 卡片逐步出现）。
- **动态最大等待时间**：`max_wait = min(30min, max(10min, total_pages * 6min))`。
- **计时基准**：优先使用后端返回的 `elapsed_ms`（避免后台 Tab 降频导致前端 wall time 虚高）。
- **降频轮询**：0–2min 每 2s；2–10min 每 5s；10min+ 每 10s。

### 4.2 Progressive disclosure（逐页披露）

- Page 1 先可看可点可问；Page 2/3 后台继续补齐。
- “新页到达”的提示可后置，但卡片更新必须可靠。

### 4.3 Two result pages（逐页披露页 vs 汇总最终页）

- `批改结果页面（逐页披露）`与`批改结果页面（汇总/最终）`是**两个不同 UI 页面**。
- 两个页面都必须支持：
  - 点击题目 → 题目详情
  - 题目卡点击 `问问AI` → `AI辅导`

### 4.4 AI辅导（整页；按题上下文；历史可续）

- `AI辅导`为整页跳转，不做 Drawer/Modal。
- 入口只有两处：
  - `批改结果页面（逐页披露/汇总）`题目卡的 `问问AI`
  - `题目详情（有图/无图）`的 `问问AI`
- 上下文只基于当前题（`submission_id + item_id`）；跨题提问需提示用户去对应题目提问。
- 每道题的聊天记录需要可续（再次进入该题仍能看到历史消息）。

### 4.5 DATA “OK” 不可逆

- `分类面板/列表页`的 `OK` 为不可逆归档（进入已掌握）。
- `已掌握面板`与`错题面板`同构：分类模块按钮 → 列表 → 题目详情。

---

## 5) Backend Contract Expectations (minimum)

### 5.1 Grade/Job

- `POST /api/v1/uploads` 返回：`upload_id / page_image_urls / total_pages`
- `POST /api/v1/grade` 返回：`job_id`（前端默认强制异步）
- `GET /api/v1/jobs/{job_id}` 返回至少要包含：
  - `status`、`elapsed_ms`、`total_pages`、`done_pages`
  - `question_cards[]`（至少包含：`item_id / question_number / page_index / verdict / answer_state`）

### 5.2 Submissions history（批改历史记录）

- `GET /api/v1/submissions` 列表必须包含可展示的：
  - `批改编号`（`display_id/short_id`）+ `created_at/subject/total_pages/...`
- `GET /api/v1/submissions/{submission_id}` 详情快照供历史详情页秒开与回放。

### 5.3 DATA archive（错题/已掌握/分类）

后端需提供可支撑以下能力的数据源/API（路径可调整，但能力必须存在）：

- 错题/已掌握的**分类模块**统计与入口参数（用于渲染分类按钮）
- 分类列表（题目列表）查询（支持点入题目详情）
- `OK` 不可逆归档写入与查询（mastered）

### 5.4 Reports（分析/报告）

- `分析页面`参数固定：科目 + 周期（3/7/30）
- Start 后需可直达 `报告详情页`（返回 `report_id` 或可查到最终 report）
- `报告记录列表`需可查询历史报告（含 `报告编号 display_id/short_id`）

---

## 6) Deferred (explicitly not blocking this spec)

- `复核卡（Review）`的成本/开关策略：不阻塞前端 IA 与 UI 主链路，后续再定。
