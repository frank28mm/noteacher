# 作业批改 Agent｜PRD（Claude Agent SDK，识卷优先）

## 1. 目标与范围
- **使命**：把用户上传的一张作业照（印刷体+手写体）**准确还原为结构化数据**（题干/选项/作答/公式/位置/置信度/证据），为后续判题、错因、讲解提供“干净可信”的输入。
- **本期范围（MVP）**：版面/题块定位 → 多引擎 OCR 融合 → 公式识别与等价校验 → 质量门与复核建议 → 产出唯一权威 **识卷JSON**。  
- **暂缓/接口预留**：判题、错因分析、讲解（第二阶段基于识卷JSON接力）。

## 2. 成功指标（KPI）
- **版面检测 F1** ≥ 0.95（在规定拍摄规范下）
- **印刷体 WER** ≤ 2%（词错误率）
- **手写体 CER** ≤ 6%（字符错误率，结合易混字典评估）
- **公式等价率** ≥ 97%（基于符号树/数值抽样判等价）
- **致命错误率** ≤ 0.5%（导致后续判定失真的识别级错误）
- **低置信度率** 10–20%（进入复核的人机协同比例，可调）

## 3. 技术路线（Claude Agent SDK）
- **Orchestrator（主编排，SDK 实现）**  
  - 调用外部 OCR 适配器（百度/DeepSeek/公式专用）  
  - 结果 **对齐/投票/规范化/置信度计算**  
  - 触发 **校验与质量门 subagents**，生成**复核建议**  
  - 产出 **RecognitionPayload（识卷JSON）**
- **Programmatic Subagents（代码内定义 `agents` 参数）**
  1) `layout-agent`：版面/题块定位（题号/题干/选项/答题区/解析区/公式片段）
  2) `ocr-merge-agent`：多引擎结果 **对齐 + 融合 + 冲突标注 + n-best**  
  3) `math-validate-agent`：LaTeX→语法树，**展开/因式/约分 + 数值抽样**双路径自校验  
  4) `quality-gate-agent`：质量门与**复核建议**（重拍/圈选/手改），产出 `need_review`
- **外部 API**：OCR（印刷体/手写体/公式）≥2家；后续可接 CAS/相似题。  
- **权限**：每个子代理**最小白名单**（只读 HTTP/Read），不授予写盘/执行。

## 4. 数据契约（识卷输出为一等公民）
```json
{
  "submission_id": "S001",
  "page_quality": { "blur": 0.08, "skew_deg": 1.5, "occlusion": 0.0, "retake_advice": "" },
  "questions": [
    {
      "qid": "Q1",
      "type": "mcq|numeric|open",
      "regions": {
        "stem":   {"bbox":[x,y,w,h], "text":"...", "latex":"", "conf":0.98, "evidence":"uri/crop1.jpg"},
        "options":[{"key":"A","text":"...","conf":0.99,"evidence":"uri/a.jpg"}],
        "answer_area":{"bbox":[...],"mode":"handwriting"}
      },
      "student_answer": {
        "raw":"B",
        "conf":0.96,
        "alts":["8","B"],
        "ambiguous_tokens":["B/8"],
        "evidence":"uri/ans.jpg"
      },
      "normalization": { "text_norm":"...", "latex_norm":"..." },
      "validations": [
        {"kind":"duplicate-options-check","status":"pass"},
        {"kind":"math-equivalence","status":"pass"}
      ],
      "need_review": false
    }
  ]
}
```

## 5. 流程与组件
1) **预处理**：裁边、去透视、去噪/二值、直线检测；输出清洁图 + 质量评分  
2) **版面理解（Where）**：题块树与 bbox（题号/题干/选项/答题/解析/公式）  
3) **多引擎 OCR（What）**：印刷体×2、手写体×2、公式优先 LaTeX，每条含 `conf` 与 `alts`  
4) **对齐与融合**：编辑距离/形似映射（1↔l、5↔s、x↔×、-↔–、全角/半角、上标^）；投票与冲突标注；规范化（升幂/空白规则）  
5) **可计算校验**：表达式双路线（展开 vs 因式/约分）+ 数值抽样；不通过→降置信度  
6) **质量门**：综合 conf/冲突/校验 → `need_review=true` 并生成**复核建议**（重拍/圈选/手改）  
7) **输出**：`RecognitionPayload` + 处理日志（可审计）

## 6. 对外接口（Agent 服务）
- `POST /api/recognize`  
  - **入参**：`{ images: string[], subject: "math" }`  
  - **出参**：`RecognitionPayload`
- （预留）`POST /api/grade`（Phase 2：识卷JSON → 判题JSON）  
- （预留）`POST /api/explain`（Phase 2：讲解卡）

## 7. 配置与模型
- **OCR_PROVIDER**：`baidu|deepseek|mathpix|...`  
- **MODEL_BY_AGENT**：`layout|ocr-merge|math-validate|quality-gate` 各自可设 `sonnet/opus/haiku`  
- **复核阈值**：`CONFIDENCE_REVIEW = 0.85`  
- **歧义字典**：可配置 JSON（1↔l、5↔s、x↔×、-↔–、"."↔","、上标^ 等）

## 8. 评测与验收
- **数据集**：≥200 页金标（含 bbox、转录、公式等价标准）  
- **度量**：版面F1、WER/CER、等价率、致命错误率、低置信度率、端到端通过率  
- **一票否决**：致命错误率 > 0.5% 视为不达标

## 9. 里程碑（MVP→可上线）
| 周 | 交付 |
|---|---|
| W1 | 契约冻结、OCR 适配器（≥2家）、预处理、评测工具 |
| W2 | 对齐融合 + 歧义字典 + 质量门（KPI 基线） |
| W3 | 公式等价校验（双路线+抽样）+ 证据裁片 |
| W4 | 低置信度复核流（前端最小圈选/点选支持）+ 日志/监控 → **MVP 验收** |

## 10. 日志、监控与隐私
- **日志**：请求ID、OCR回包摘要、冲突位、阈值决策、子代理调用链  
- **监控**：实时 WER/CER/等价率/致命错误率看板；低置信度占比  
- **隐私**：最小化存储；裁片与原图分区加密；可配置数据保留期与脱敏策略

## 11. 主要风险与对策
- **手写体混淆/脏污**：歧义字典 + 质量门 + 重拍建议卡  
- **复杂版面**：先约束拍摄模板；逐步灰度放开（表格/多栏/拼接）  
- **公式错译**：引入公式专用 OCR；用等价/抽样兜底  
- **一致性漂移**：固定评测集 + 版本回归；模型/供应商变更需复核

## 附：四个 Subagents（人设摘要）
- **layout-agent**：输出题块树（题号/题干/选项/答题/解析/公式片段）的 bbox 与类型；不做文本判定。  
- **ocr-merge-agent**：消费多引擎结果，做 token 级对齐、形似映射、投票、n-best 与冲突标注、规范化；产出 conf。  
- **math-validate-agent**：对 `latex_norm` 做展开/因式/约分与数值抽样双路径校验；回写 `validations` 与置信度修正。  
- **quality-gate-agent**：按规则与阈值给出 `need_review` 与“重拍/圈选/手改”的**具体建议**（含定位）。
