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
- **Limitations**: Base64 input failed (Ark API restriction).

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
- Chat：`POST /api/v1/chat` 使用 `session_id`（SSE）；当用户提出“看图/图形判断”时，后端会确保 qindex 切片并 relook，失败则明确说明“看不到图”
