# Chat功能问题分析报告

**报告日期**: 2025-12-14
**调查范围**: Chat功能异常及数学公式显示问题
**调查人**: Claude Code

---

## 问题概述

用户反馈了两个关键问题：

1. **数学公式显示异常**：出现了代码形式（如 `x^(6n)`）和删除线，用户体验差
2. **Chat功能逻辑混乱**：用户按提示换元后，LLM无法理解用户回答，导致对话崩溃

---

## 问题1：数学公式显示异常

### 现状分析

**问题位置**: `homework_agent/api/chat.py:334-414`

```python
def _format_math_for_display(text: str) -> str:
    """
    Make math in assistant messages more readable in demo UI:
    - Strip LaTeX delimiters like \\( \\) \\[ \\]
    - Replace a few common TeX commands with Unicode (× ÷ ± ∠ ·)
    This is best-effort and should never raise.
    """
```

**发现的问题**:

1. **LaTeX定界符处理不完整** (第345行)
   - 移除了 `\\(` `\\)` `\\[` `\\]` 定界符
   - 但没有处理 `$...$` 行内数学公式，导致 `$x^{2}$` 被保留

2. **指数转换逻辑错误** (第352-369行)
   - `_wrap_symbolic_pow` 函数试图将 `x^2` 转换为 `$x^{2}$`
   - 但这个转换**非常粗糙**，会错误地包裹已有LaTeX格式的表达式
   - 正则表达式 `r"(?<![\\$])\b([A-Za-z]|\d+|\([^\s()]{1,6}\))\s*\^\s*..."` 无法正确区分已格式化的数学表达式

3. **删除线来源不明**
   - 代码中未发现删除线处理逻辑
   - 可能来自前端渲染或LLM输出

### 根本原因

- `_format_math_for_display` 函数试图"智能"处理数学表达式，但实现过于简化
- **核心问题**：应该直接传递标准LaTeX格式 `$...$`，而不是尝试"用户友好"的转换
- 根据 `prompts.py:152` 要求，LLM输出应该使用 `$...$` 格式，但后端又在尝试"优化"，导致冲突

---

## 问题2：Chat功能逻辑混乱

### 关键证据

**日志证据** (`logs/backend.log:8-13`):
```
WARNING homework_agent.api.chat {"event":"chat_route_not_found","requested_qn":"8","available_count":7}
WARNING homework_agent.api.chat {"event":"chat_route_not_found","requested_qn":"8","available_count":7}
```

**矛盾点**：
- 用户说"第20题 我不知道怎么写"
- 用户说"哦，不是。我说的是20(2)"
- 用户说"我是在跟你说20（2）啊"
- 但日志显示系统解析的是"第8题"

### 问题分析

#### 1. 题号解析逻辑缺陷

**位置**: `homework_agent/api/chat.py:59-181`

```python
def _select_question_number_from_text(message: str, available: List[str]) -> Optional[str]:
```

**问题**:
- `_extract_requested_question_number` (第184-195行) 使用正则：`r"(?:第\s*)?(\d{1,3}(?:\s*\(\s*\d+\s*\)\s*)?(?:[①②③④⑤⑥⑦⑧⑨])?)(?:\s*题)?"`
- 正则本身可以匹配"20(2)"格式
- 但在 `_select_question_number_from_text` 中，系统会搜索**所有**可能的题号匹配
- **关键缺陷**：当用户说"第20题 我不知道怎么写"时，系统可能优先匹配了"20"，但随后对话中用户提到其他内容时，焦点题号可能被错误重置

#### 2. 题号解析逻辑混乱

**位置**: `homework_agent/api/chat.py:679-683`

```python
else:
    # Heuristic: choose best match among available numbers mentioned in the message.
    mentioned = _select_question_number_from_text(req.question, available_qnums)
    if mentioned:
        session_data["focus_question_number"] = str(mentioned)
```

**问题**:
- 当用户回答 `"t(t-8)+16?"` 时，`_select_question_number_from_text` 函数会从数学表达式中错误提取 `"8"` 或 `"16"` 作为题号
- 系统绑定了错误的题目（如第8题），然后去查找该题目的信息，自然找不到
- **核心缺陷**：系统在**每轮对话**都尝试重新解析题号，而不是保持上一轮的焦点题号

#### 3. 对话流程设计缺陷

**位置**: `homework_agent/api/chat.py:642-684`

```python
# Determine requested question number (explicit) and bind focus deterministically.
requested_qn = _extract_requested_question_number(req.question)
requested_qn = _normalize_question_number(requested_qn) if requested_qn else None
if requested_qn:
    # 用户明确指定题号 -> 绑定该题号
    session_data["focus_question_number"] = str(requested_qn)
else:
    # 用户没有明确指定题号 -> 但系统仍尝试从文本中"猜测"题号
    mentioned = _select_question_number_from_text(req.question, available_qnums)
    if mentioned:
        session_data["focus_question_number"] = str(mentioned)
```

**问题**:
- 当用户说 `"t(t-8)+16?"` 时，`_extract_requested_question_number` 返回 `None`（因为这不是明确的题号）
- 但系统没有保持上一轮的焦点题号，而是进入了 `else` 分支
- 系统调用 `_select_question_number_from_text("t(t-8)+16?", available_qnums)`，错误地从数学表达式中提取题号
- 这导致系统认为用户想聊第8题或第16题，而不是继续聊第20(2)题

---

## 根本原因总结

### 1. 数学公式显示问题

**直接原因**:
- `_format_math_for_display` 函数试图"优化"LaTeX输出，但算法错误
- 试图将 `x^2` 转换为 `$x^{2}$`，但错误包裹了已有 `$...$` 的表达式

**根本原因**:
- **设计冲突**：`prompts.py` 要求LLM输出标准LaTeX `$...$` 格式
- 但后端又试图"用户友好化"，导致格式混乱
- 应该：**完全移除 `_format_math_for_display` 的"智能"转换，只做最小必要处理**

### 2. Chat对话混乱问题

**直接原因**:
- 当用户回答 `"t(t-8)+16?"` 时，系统错误地从数学表达式中提取了 `"8"` 或 `"16"` 作为题号
- 系统绑定了错误的题目（如第8题），然后去查找该题目的信息，自然找不到

**根本原因**:
- **题号解析逻辑混乱**：`_select_question_number_from_text` 函数会从**任何包含数字的文本**中提取题号，包括数学表达式中的数字
- **对话流程设计缺陷**：系统在**每轮对话**都尝试重新解析题号，而不是保持上一轮的焦点题号
- **缺乏对话上下文理解**：当用户说 `"t(t-8)+16?"` 时，这是在回答上一轮关于第20(2)题的换元引导，但系统没有识别到这是对之前话题的延续

**具体流程**：
1. 第一轮：用户说"第20题"，系统绑定焦点题号为"20"
2. 第二轮：用户说"哦，不是。我说的是20(2)"，系统切换到"20(2)"
3. 第三轮：LLM引导"把$x^2 + x$换成$t$"，用户回答"t(t-8)+16?"
4. **关键错误**：系统调用 `_select_question_number_from_text("t(t-8)+16?", available_qnums)`，从中错误提取了 `"8"` 或 `"16"`
5. 系统认为用户想聊第8题或第16题，但这些题目不存在（或不是用户真正想问的）
6. 系统返回"未能在本次批改结果里定位到第8题"

---

## 解决方案

### 方案1：修复数学公式显示 (高优先级)

**实施**:
1. **完全重写** `_format_math_for_display` 函数
2. 只保留最小必要处理：
   ```python
   def _format_math_for_display(text: str) -> str:
       if not text:
           return text
       # 只移除过时的 \\( \\) 定界符，保留 $...$
       s = str(text)
       s = s.replace("\\(", "").replace("\\)", "").replace("\\[", "").replace("\\]", "")
       return s
   ```
3. **移除所有"智能"转换逻辑**，特别是 `_wrap_symbolic_pow` 函数
4. 确保LLM输出标准LaTeX `$x^{2}$` 格式直接显示

### 方案2：修复Chat焦点题号绑定 (高优先级)

**核心原则**：只有当用户**明确**指定题号时才切换焦点，否则保持上一轮的焦点题号。

**实施**:

1. **修改焦点题号保持逻辑** (chat.py:679-683):
   ```python
   # 当前代码（错误）
   else:
       # Heuristic: choose best match among available numbers mentioned in the message.
       mentioned = _select_question_number_from_text(req.question, available_qnums)
       if mentioned:
           session_data["focus_question_number"] = str(mentioned)

   # 建议修改为（正确）
   else:
       # 用户没有明确指定新题号 -> 保持上一轮的焦点题号
       # 不重新解析题号！
       # session_data["focus_question_number"] 保持不变
       pass
   ```

2. **改进题号解析函数**（如果需要保留 `_select_question_number_from_text`）：
   - 只在用户明确说"第X题"、"聊X题"、"讲X题"时才提取题号
   - 避免从数学表达式（如 `"t(t-8)+16"`）中提取数字作为题号

3. **添加调试日志**：
   ```python
   log_event(
       logger,
       "chat_focus_question_maintained",
       request_id=request_id,
       session_id=session_id,
       focus_question_number=session_data.get("focus_question_number"),
       user_message=req.question[:50],  # 只记录前50字符
   )
   ```

4. **错误处理优化**（当确实找不到题号时）：
   ```python
   msg = (
       f"你想继续聊第{session_data.get('focus_question_number')}题吗？"
       + (f" 还是想聊其他题？当前可聊题号：{', '.join(available_qnums[:30])}。" if available_qnums else "")
   )
   ```

### 方案3：增强LLM上下文理解 (中优先级)

**注意**：这是辅助措施，主要问题已通过方案2解决。

**实施**:
1. **改进提示词** (在 `prompts.py` 的 `SOCRATIC_TUTOR_SYSTEM_PROMPT` 中添加):
   ```
   <context_rules>
   - 若用户正在回答你的引导问题（如换元、填空、选择等），请基于用户的回答继续引导，不要突然切换话题或要求用户提供新信息
   - 若用户说"不是...是..."，这是对题干的更正，请使用更正后的题干继续辅导
   - 若用户给出中间步骤（如"t(t-8)+16"），这是换元后的结果，请基于此继续引导下一步
   </context_rules>
   ```

2. **增加对话状态标记**（可选）：
   - 在 `session_data` 中添加 `conversation_state` 字段
   - 标记当前是"题目澄清"、"解题引导"、"总结"等状态
   - 帮助LLM更好地理解对话流程

### 方案4：调试和监控改进 (中优先级)

**实施**:
1. **增加详细日志**：
   ```python
   log_event(
       logger,
       "chat_question_extraction",
       request_id=request_id,
       original_message=req.question,
       extracted_question=requested_qn,
       available_questions=available_qnums,
       selected_question=selected_q,
   )
   ```

2. **添加调试端点**：
   - 创建 `/debug/session/{session_id}` 端点
   - 返回完整的 session 状态，包括历史消息、焦点题号等

---

## 预期效果

| 修复项 | 预期效果 | 工作量 |
|--------|----------|--------|
| 修复 `_format_math_for_display` | 数学公式正常显示为 `$x^{2}$` 格式，无删除线 | 0.5天 |
| 修复题号绑定逻辑 | Chat对话不再混乱，当用户说 "t(t-8)+16" 时系统保持第20(2)题焦点 | 1天 |
| 优化提示词（辅助） | LLM更好地理解用户的换元等操作 | 0.5天 |
| 增加调试日志 | 方便定位后续问题 | 0.5天 |
| **总计** | | **2.5天** |

---

## 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 修改后公式显示更差 | 低 | 高 | 保留旧版本函数，添加 feature flag |
| Chat对话能力下降 | 中 | 高 | 先在测试环境验证，逐步灰度 |
| 破坏现有功能 | 低 | 中 | 增加单元测试，回归测试 |

---

## 建议实施顺序

1. **立即修复** (1天)：
   - 重写 `_format_math_for_display` 函数
   - 修复题号解析逻辑

2. **短期优化** (1-2天)：
   - 改进提示词
   - 增加详细日志

3. **中期改进** (1周内)：
   - 添加调试端点
   - 完善监控和告警

---

**报告结论**: 问题根源明确，解决方案可行。建议立即开始修复，优先级高于新功能开发。