# 前端业务流程与后端需求对齐报告
**报告日期**: 2026-01-11
**基于**: Excalidraw 信息架构、用户7点反馈、现有代码库审查

---

## 执行摘要

本报告基于以下信息源综合编制：
1. Excalidraw 流程图描述
2. 用户 7 点关键反馈要求
3. [frontend_design_spec_v2.md](../frontend_design_spec_v2.md) (v2.2)
4. Frontend source of truth: [frontend_design_spec_v2.md](../frontend_design_spec_v2.md)  
   (Archived v2.2 history: [frontend_architecture_20260111_v2_2_deprecated.md](../archive/frontend_architecture_20260111_v2_2_deprecated.md))
5. 后端代码审查 ([grade.py](../../homework_agent/api/grade.py), [submissions.py](../../homework_agent/api/submissions.py), [chat.py](../../homework_agent/api/chat.py), [report_features.py](../../homework_agent/services/report_features.py))

**结论**: 前端主链路（上传→批改→结果→辅导）已有后端支撑，但报告模块需补充时间序列数据，结果页需增加 Toggle 切换功能。

---

## 第一部分：前端业务流程与界面跳转

### 1.1 主链路：首页 → 批改 → 结果 → 辅导

```
┌─────────────┐
│   Home      │ → [SCAN/UPLOAD] → (上传过渡态) → Analyzing (批改中)
│  (首页)     │                                        ↓
│             │ ←────────────────────────────────── Result (结果页)
│ [Recent]    │                                        ↓
│  Activity   │ ←─────── [Back] ←─────────────────────┘
└─────────────┘                  ↓
                  [Click Card] → Chat Drawer (辅导)
                                ↓
                          [Close] → 返回 Result
```

**页面跳转规则**:

| 当前页面 | 触发操作 | 目标页面 | 后端依赖 |
|---------|---------|---------|---------|
| Home | SCAN/UPLOAD | Uploading → Analyzing | `POST /uploads` → `POST /grade` |
| Analyzing | 轮询完成 | Result | `GET /jobs/{job_id}` (轮询) |
| Result | 点击题目卡 | Question Detail | 从 `question_cards` 获取详情 |
| Result | 问老师 | Chat Drawer | `POST /chat` |
| Chat Drawer | 关闭 | 返回 Result | 无 (前端状态管理) |
| Home | Recent Activity | History Detail | `GET /submissions/{id}` |

**可随时返回 Home 的规则**:
- 用户可在任何流程点通过底部导航栏返回 Home
- Home 会显示"继续"入口（如果有 `job_id` 正在处理）
- 通过 `localStorage.last_job_id` 持久化实现断点续传

### 1.2 次级链路：错题本与历史记录

```
┌─────────────┐
│ Mistake Tab │ → [List] → [Click Item] → Mistake Detail Modal
│  (错题本)   │                           ↓
└─────────────┘                    [Ask Teacher] → Chat Drawer
```

**后端依赖**:
- 列表: `GET /api/v1/submissions` (按 `subject` 过滤)
- 详情: `GET /api/v1/submissions/{submission_id}` (返回快照，不重建 job)

### 1.3 报告链路

```
┌─────────────┐
│ Report Tab  │ → [Filter: Subject + 3/7/30天] → Check Eligibility
│  (报告页)   │                                     ↓
└─────────────┘                           [Generate Report] → Report Detail
                                                  ↓
                                            (展示趋势图、知识点、AI评价)
```

**后端依赖**:
- 解锁检查: `GET /api/v1/reports/eligibility`
- 生成报告: `POST /api/v1/reports` (参数: `window_days`, `subject`)
- 报告详情: `GET /api/v1/reports/{report_id}`

---

## 第二部分：前端需求规格（与当前代码对比）

### 2.1 结果页（Result Screen）—— **需调整**

| 需求项 | 用户要求 | 当前代码状态 | 前端需实现 |
|-------|---------|-------------|-----------|
| 视图切换 | 默认显示错题，支持切换到"全部" | 仅有 Mistakes 视图 | **需新增**: Toggle 组件，`Mistakes` (默认) / `All` |
| 多页渐进披露 | 占位卡 → 判定卡 → 复核卡 | ✅ 已实现三态卡片 | ✅ 无需修改 |
| 页面进度指示 | 顶部 Tabs + 左侧页条 | ✅ `page_summaries` 已返回 | ✅ 无需修改 |
| 轮询停止条件 | `done/failed` 且无 `review_pending` | ✅ 已实现 | ✅ 无需修改 |
| 最小展示时间 | 取消强制 1.5s，仅防闪屏 | 当前有 1.5s 强制 | **需调整**: 仅在极快完成时延迟防闪 |

**Toggle 切换逻辑**:
```javascript
// 前端过滤逻辑（基于 question_cards）
const showMistakes = toggleValue === 'mistakes';
const filteredCards = question_cards.filter(card => {
  if (!showMistakes) return true; // All 模式显示全部
  // Mistakes 模式：排除 correct 且非 blank 的题目
  return !(
    card.verdict === 'correct' &&
    card.card_state === 'verdict_ready' &&
    card.answer_state !== 'blank'
  );
});
```

### 2.2 批改中（Analyzing）—— **微调**

| 需求项 | 用户要求 | 当前代码状态 | 调整 |
|-------|---------|-------------|-----|
| 强制停留 | 取消 1.5s 强制，仅防闪屏 | 硬编码 1.5s | 前端改为: `if (elapsed < 500) await delay(500 - elapsed)` |

### 2.3 旋钮选择器（报告页）—— **H5 降级方案**

| 方案 | 实现方式 | 适用场景 |
|-----|---------|---------|
| 原设计 | Framer Motion 旋钮，拖拽旋转 | 原生 APP |
| H5 降级 | 点击式旋钮：每次点击旋转一格 | H5/Web |

**H5 旋钮逻辑**:
```javascript
// 三个选项: [3天, 7天, 30天]
const periods = [3, 7, 30];
let selectedIndex = 1; // 默认 7 天

const rotate = () => {
  selectedIndex = (selectedIndex + 1) % periods.length;
  // 触发旋转动画 + 更新 UI
};
```

### 2.4 Chat 辅导—— **核心调整**

| 需求项 | 用户要求 | 当前代码状态 | 需调整 |
|-------|---------|-------------|-------|
| 作用域 | 仅限当前题目 (`submission_id + item_id`) | ✅ 已支持 `context_item_ids` | ✅ 无需修改 |
| 切片图片 | **不再返回切片截图** | 当前可能有切片 | **后端需调整**: chat.py 响应中移除 `slice_images` |
| 会话持久化 | 每题独立历史，支持重入 | ✅ 24h TTL session | ✅ 无需修改 |
| 苏格拉底式 | **不给答案，仅引导** | 部分回复可能露答案 | **后端需调整**: prompt 加强 |
| 跨题重定向 | 用户问非本题，引导去对应题目 | ❌ 未实现 | **需新增**: 意图检测 + 重定向逻辑 |

**Chat 入口与状态管理**:
```javascript
// Zustand Store 结构
interface ChatStore {
  sessions: Map<string, ChatSession[]>; // key: `${submission_id}_${item_id}`
  currentSession: { submission_id, item_id } | null;

  enterChat: (submission_id: string, item_id: string) => void;
  exitChat: () => void;
  appendMessage: (msg: ChatMessage) => void;
  // 从 submission 快照恢复会话
  rehydrate: (submission_id: string, item_id: string) => Promise<void>;
}
```

### 2.5 报告详情页—— **后端需补充数据**

| UI 元素 | 用户要求 | 后端数据支持状态 | 依赖字段 |
|--------|---------|----------------|---------|
| 正确率仪表盘 | ✅ 需求 | ✅ 已支持 | `stats.overall.accuracy` |
| 薄弱知识点 Top 3 | ✅ 需求 | ✅ 已支持 | `stats.knowledge_mastery.rows[:3]` |
| 错因分布柱状图 | ✅ 需求 | ⚠️ 基础支持 | `stats.process_diagnosis.severity_counts` |
| 知识点趋势图 | ✅ 需求 | ❌ **缺失** | **需新增**: `stats.knowledge_trends_top5` |
| 错因趋势图 | ✅ 需求 | ❌ **缺失** | **需新增**: `stats.cause_trends_top3` |
| AI 评价文本 | ✅ 需求 | ✅ 已支持 | `report.content` |

---

## 第三部分：后端补充工作清单

### 3.1 P0: 结果页 Toggle 支持（前端为主）

**目标**: 支持结果页在"错题"和"全部"之间切换

**现状**: `question_cards` 已包含所有题目，前端过滤即可

**工作内容**:
- ❌ **无后端改动**，前端基于现有 `verdict`/`card_state` 字段过滤
- 过滤规则：
  - Mistakes 模式：`verdict in {incorrect, uncertain} OR card_state in {review_pending, review_ready, review_failed}`
  - All 模式：显示全部卡片

### 3.2 P0: Chat 调整（苏格拉底式 + 无切片）

**目标**: 确保 Chat 回复符合"苏格拉底引导式"原则

**需调整文件**: [homework_agent/api/chat.py](../../homework_agent/api/chat.py)

**工作内容**:

1. **移除切片图片响应**
   - 搜索 `slice_images` 相关逻辑
   - 确保 SSE 响应中不返回任何图片 URL

2. **加强 Prompt（防露答案）**
   - 在 system prompt 中明确：
     - "不得直接给出最终答案"
     - "必须通过反问引导用户自己思考"
     - "只能提示思考方向，不能替用户完成计算/推导"

3. **跨题重定向逻辑**
   - 检测用户消息是否提及"第X题"
   - 若提及当前题以外，返回重定向消息：
     ```
     "看起来你在问第 {detected_question} 题，请在结果页点击该题的卡片进入对应的对话。"
     ```

### 3.3 P1: 报告时间序列数据（新增）

**目标**: 支持报告详情页的两张趋势图

**需调整文件**: [homework_agent/services/report_features.py](../../homework_agent/services/report_features.py)

**工作内容**:

1. **知识点趋势 Top 5** (`knowledge_trends_top5`)
   ```python
   # 需新增逻辑
   # 数据源: question_attempts 表
   # 聚合维度: (created_at, knowledge_tags_norm)
   # 时间分桶:
   #   - 若 submissions 数 <= 15: 按 submission 粒度
   #   - 若 submissions 数 > 15: 按 3 天分桶
   # 返回格式:
   {
     "knowledge_trends_top5": [
       {
         "tag": "勾股定理",
         "timepoints": [
           {"date": "2026-01-01", "accuracy": 0.75, "sample_size": 4},
           {"date": "2026-01-04", "accuracy": 0.83, "sample_size": 6},
           # ...
         ]
       },
       # ... Top 5 知识点
     ]
   }
   ```

2. **错因趋势 Top 3** (`cause_trends_top3`)
   ```python
   # 需新增逻辑
   # 数据源: question_steps 表
   # 聚合维度: (created_at, diagnosis_codes)
   # 同样的时间分桶逻辑
   # 返回格式:
   {
     "cause_trends_top3": [
       {
         "cause": "calculation_error",
         "cause_label": "计算错误",  # 中文标签
         "timepoints": [
           {"date": "2026-01-01", "count": 3},
           {"date": "2026-01-04", "count": 1},
         ]
       },
       # ... Top 3 错因
     ]
   }
   ```

3. **错因分类 Taxonomy 扩充**
   - 当前仅有基础的 `calculation_error`
   - 需定义完整的中文分类体系，例如：
     - `calculation_error` → "计算错误"
     - `concept_misunderstanding` → "概念理解偏差"
     - `method_inappropriate` → "解题方法不当"
     - `carelessness` → "粗心大意"
     - `incomplete_reasoning` → "推理不完整"

### 3.4 P1: 报告参数调整（固定窗口）

**目标**: 报告仅支持 3/7/30 天，且必须分科目

**现状**: [report_features.py](../../homework_agent/services/report_features.py) 已接受 `window` 参数

**工作内容**:
- ❌ **无需修改**，前端调用时固定传入 `window_days={3,7,30}` + `subject={math,english}`
- 后端仅需确保按 `subject` 过滤 `question_attempts` 和 `question_steps`

### 3.5 P2: Analyzing 最小展示时间调整（前端为主）

**目标**: 取消强制 1.5s，仅在极快完成时防闪屏

**工作内容**:
- ❌ **无后端改动**，前端自行决定展示时长
- 前端逻辑：
  ```javascript
  const startTime = Date.now();
  // ... 轮询直到完成
  const elapsed = Date.now() - startTime;
  if (elapsed < 500) {
    await delay(500 - elapsed); // 仅防闪屏
  }
  // 跳转到结果页
  ```

---

## 第四部分：数据流完整性检查

### 4.1 批改主链路数据流

```
用户上传图片
    ↓
POST /uploads → upload_ids
    ↓
POST /grade (images: upload_ids) → job_id
    ↓
GET /jobs/{job_id} 轮询
    ↓
返回 question_cards (三态: placeholder → verdict → review)
    ↓
persist_submission → submissions 表 (持久化快照)
    ↓
GET /submissions/{id} → 历史查看（不重建 job）
```

**检查结果**: ✅ 完整，无缺口

### 4.2 辅导 Chat 数据流

```
用户点击"问老师" (携带 submission_id + item_id)
    ↓
POST /chat
    ├─ context_item_ids: [item_id]
    ├─ submission_id: xxx (可选，用于历史重入)
    ↓
SSE 流式响应
    ├─ 从 session 恢复历史 (若 session_id 有效)
    ├─ 或从 submission 快照重建 (submission_id 模式)
    ↓
Chat Drawer 显示对话历史
```

**检查结果**: ✅ 完整，但需补充:
- ⚠️ 移除切片图片响应
- ⚠️ 加强苏格拉底式 prompt
- ⚠️ 跨题重定向逻辑

### 4.3 报告数据流

```
用户选择科目 + 时间窗口 (3/7/30 天)
    ↓
GET /reports/eligibility → 检查 submissions 数量
    ↓
POST /reports (window_days, subject)
    ↓
异步生成 report_job
    ├─ Features Layer: report_features.py (确定性统计)
    │  ├─ overall ✅
    │  ├─ knowledge_mastery ✅
    │  ├─ type_difficulty ✅
    │  ├─ process_diagnosis ✅ (但需扩充 taxonomy)
    │  └─ **trends ❌ (需新增)**
    └─ Narrative Layer: LLM 生成评价文本 ✅
    ↓
GET /reports/{report_id} → 展示报告
```

**检查结果**: ⚠️ 缺失时间序列数据

---

## 第五部分：前端开发优先级

### P0（必须，阻塞主流程）

1. **结果页 Toggle 组件**
   - 文件: `features/result/ResultScreen.tsx`
   - 状态: `viewMode: 'mistakes' | 'all'`
   - 依赖: 无（前端过滤）

2. **Chat 会话管理**
   - 文件: `store/chatStore.ts`
   - 状态: 按 `submission_id + item_id` 双键存储历史
   - 持久化: `localStorage` + 后端 session

3. **Chat 苏格拉底式 Prompt**
   - 文件: 后端 `chat.py`
   - 修改: system prompt 强化"不给答案"

### P1（重要，影响体验）

4. **报告趋势图组件**
   - 文件: `features/report/ReportDetail.tsx`
   - 图表库: Recharts
   - 依赖: **后端需补充** `knowledge_trends_top5` 和 `cause_trends_top3`

5. **旋钮选择器（H5 降级版）**
   - 文件: `features/report/ReportFilter.tsx`
   - 交互: 点击旋转（非拖拽）

6. **Analyzing 防闪屏逻辑**
   - 文件: `features/grading/AnalyzingScreen.tsx`
   - 逻辑: `if (elapsed < 500) await delay(500 - elapsed)`

### P2（增强，可延后）

7. **Chat 跨题重定向**
   - 文件: 后端 `chat.py`
   - 逻辑: 意图检测 + 重定向消息

8. **骨架屏加载**
   - 文件: 各列表页
   - 替换 Spinner

---

## 第六部分：后端开发优先级

### P0（阻塞前端）

| 任务 | 文件 | 工作量 | 状态 |
|-----|-----|-------|-----|
| Chat 移除切片图片 | `chat.py` | 小 | ⚠️ 待实现 |
| Chat 苏格拉底 Prompt | `chat.py` | 小 | ⚠️ 待实现 |

### P1（影响报告功能）

| 任务 | 文件 | 工作量 | 状态 |
|-----|-----|-------|-----|
| 知识点趋势聚合 | `report_features.py` | 中 | ❌ 待实现 |
| 错因趋势聚合 | `report_features.py` | 中 | ❌ 待实现 |
| 错因 Taxonomy 扩充 | `resources/knowledge_taxonomy_v0.json` | 小 | ❌ 待实现 |
| Chat 跨题重定向 | `chat.py` | 中 | ⚠️ 待实现 |

### P2（优化）

| 任务 | 文件 | 工作量 | 状态 |
|-----|-----|-------|-----|
| Analyzing 最小时间 | 前端自行处理 | 无 | ✅ 无需后端改动 |

---

## 第七部分：风险与决策

### 7.1 已识别风险

| 风险 | 影响 | 缓解措施 |
|-----|-----|---------|
| 报告趋势图数据缺失 | 无法展示趋势图 | P1 优先级实现时间序列聚合 |
| Chat 可能露答案 | 违反产品原则 | P0 优先级强化 Prompt |
| 跨题 Chat 重定向未实现 | 用户困惑 | P2 优先级（可延后） |

### 7.2 待决策事项

1. **H5 旋钮降级方案确认**
   - 是否接受点击式（非拖拽）旋转？
   - 若否，需投入更多时间实现 Web 拖拽物理

2. **错因 Taxonomy 范围**
   - 是否仅补充 3-5 个常见分类？
   - 是否需要更细粒度的二级分类？

3. **报告时间序列分桶策略**
   - 当前: ≤15 submissions 按次，>15 按 3 天分桶
   - 是否需要 1 天/7 天 等其他分桶粒度？

---

## 第八部分：附录

### A. 关键 API 端点摘要

| 端点 | 用途 | 状态 |
|-----|-----|-----|
| `POST /uploads` | 图片上传 | ✅ 已实现 |
| `POST /grade` | 创建批改任务 | ✅ 已实现 |
| `GET /jobs/{id}` | 轮询任务状态 | ✅ 已实现 |
| `GET /submissions` | 历史列表 | ✅ 已实现 |
| `GET /submissions/{id}` | 历史详情 | ✅ 已实现 |
| `POST /chat` | AI 辅导（SSE） | ✅ 已实现（需调优） |
| `GET /reports/eligibility` | 报告解锁检查 | ✅ 已实现 |
| `POST /reports` | 生成报告 | ✅ 已实现 |
| `GET /reports/{id}` | 报告详情 | ✅ 已实现 |

### B. 数据库表依赖

| 表名 | 用途 | 状态 |
|-----|-----|-----|
| `submissions` | 作业快照（主数据源） | ✅ 已创建 |
| `question_attempts` | 每题统计（报告分母） | ✅ 已创建 |
| `question_steps` | 每步诊断（错因分析） | ✅ 已创建 |
| `reports` | 报告结果 | ✅ 已创建 |
| `report_jobs` | 报告生成任务 | ✅ 已创建 |
| `mistake_exclusions` | 错题过滤（不影响历史） | ✅ 已创建 |

### C. 前端状态管理结构

```typescript
// Zustand Stores
interface TaskStore {
  jobId: string | null;
  status: 'uploading' | 'analyzing' | 'done' | 'failed';
  questionCards: QuestionCard[];
  setJobId: (id: string) => void;
  updateCards: (cards: QuestionCard[]) => void;
}

interface SubmissionStore {
  submissions: Submission[];
  lastFetch: number | null;
  fetchSubmissions: () => Promise<void>;
}

interface ChatStore {
  sessions: Map<string, ChatSession[]>;
  currentSession: { submissionId: string; itemId: string } | null;
  enterChat: (submissionId: string, itemId: string) => Promise<void>;
  exitChat: () => void;
  rehydrate: (submissionId: string, itemId: string) => Promise<void>;
}

interface ReportStore {
  eligibility: EligibilityInfo | null;
  currentReport: Report | null;
  filter: { subject: string; windowDays: number };
  checkEligibility: () => Promise<void>;
  generateReport: () => Promise<void>;
}
```

---

**报告结束**

*本报告基于代码审查至 2026-01-11，如有后续代码变更需重新对齐。*
