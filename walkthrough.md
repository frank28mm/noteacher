# Verification Report: Qwen3-VL & Doubao Vision

## 1. Model Switch: Qwen/Qwen3-VL-32B-Thinking
**Objective**: Replace `Qwen/Qwen2.5-72B-Instruct` with `Qwen/Qwen3-VL-32B-Thinking` for all reasoning tasks (Grading + Socratic).

### Grading (Math/English)
- **Status**: ✅ Verified
- **Result**: Successfully parsed JSON output for both Math and English grading.
- **Observations**: Model correctly identified calculation errors in Math and translation errors in English.

### Socratic Tutor
- **Status**: ⚠️ Verified (Unstable)
- **Issues**: The "Thinking" model exhibits high latency (>60s), causing frequent `Connection error` or timeouts during the multi-turn Socratic flow verification script.
- **Mitigation**: 
    - Increased API timeout to 300s.
    - Increased `max_tokens` to 2000 to accommodate thinking process.

## 2. Vision Integration

### A. Doubao (Ark)
**Model**: `doubao-seed-1-6-vision-250815`
- **Status**: ✅ Verified with URL
- **Method**: Validated using a public HTTP URL (Baidu Logo).
- **Result**: Successfully recognized the text "Baidu".
- **Notes**: URL 优先；当供应商抓取 URL 不稳定/超时时，可用 Data-URL(base64) 作为后端兜底（绕开对方抓 URL）。

### B. Qwen3-VL (SiliconFlow)
**Model**: `Qwen/Qwen3-VL-32B-Thinking`
- **Status**: ✅ Verified (Slow)
- **Method**: Validated using a public HTTP URL (Baidu Logo).
- **Result**: detailed description of the logo (paw print, colors, text).
- **Note**: High latency (~40s); requires client timeout >= 120s (set to 300s).

## Next Steps
- Proceed to **UI Demo** (`demo_ui.py`) to test Socratic Tutor interactively, which allows for manual retries and better visibility than a CLI script.

## Current E2E (Recommended Path)
- Upload：`POST /api/v1/uploads`（后端落 Supabase Storage，返回 `upload_id + page_image_urls`）
- Grade：`POST /api/v1/grade` 使用 `upload_id`（后端反查 images），返回 `session_id + vision_raw_text + 批改结果`
- Chat：`POST /api/v1/chat` 使用 `session_id`（SSE）；不实时看图，只读取 `/grade` 产出的 `judgment_basis + vision_raw_text`。若 `visual_facts` 缺失，仍给出结论但提示“视觉事实缺失，本次判断仅基于识别文本”；若题目未定位，响应会携带候选题目列表供 UI 快捷选择。
