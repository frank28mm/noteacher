# Implementation Plan - Stability & Robustness Improvements

## Goal
Address critical stability issues and input validation gaps in the Service Layer (`VisionClient`, `LLMClient`) to ensure a robust foundation before building the Demo UI. This aligns with the "Stability First" approach. **原则：URL First，Base64 仅兜底；单文件大小上限 20 MB；Qwen3 为主力模型（非兜底）**。

## Proposed Changes

### 1. Vision Input Validation & Hardening
#### [MODIFY] [homework_agent/services/vision.py](file:///Users/frank/Documents/网页软件开发/作业检查大师/homework_agent/services/vision.py)
*   **Doubao (Ark) Guardrail**: 仅接受公网 HTTP/HTTPS URL；base64 直接抛错，提示“请上传到 OSS 后提供 URL”。
*   **Qwen (Silicon) Policy**: Qwen3 为主力，推荐 URL；Base64 仅兜底，自动剥离 `data:image/...;base64,` 前缀，若解析失败提示改用 URL。
*   **Validation**: 校验 HTTP/HTTPS，拒绝 127/localhost/内网；单文件大小上限 20 MB；提示需公网可达，避免 data: 前缀。

### 2. LLM/Vision Retry Logic
#### [MODIFY] [homework_agent/services/llm.py](file:///Users/frank/Documents/网页软件开发/作业检查大师/homework_agent/services/llm.py) & [homework_agent/services/vision.py](file:///Users/frank/Documents/网页软件开发/作业检查大师/homework_agent/services/vision.py)
*   Ensure the `max_retries` parameter (already present in function signatures) is actually utilized.
*   Implement a simple retry loop (with exponential backoff, e.g., `tenacity` or custom loop) around the OpenAI client calls to handle transient network errors (`APIConnectionError`, `timeout`)，不对 4xx/校验失败重试。
*   Logging: 在重试前/失败时记录 provider/model/operation，便于观察重试来源。

### 3. Redis Verification (Optional but Recommended)
*   If `REDIS_URL` is configured, verify connection in `homework_agent/utils/cache.py` on startup and log a clear warning if fallback to Memory is triggered.

## Verification Plan

### Automated Verification
1.  **Vision Validation Test**: Run a script that attempts to send Base64 to Doubao and asserts that it raises the expected `ValueError`.
2.  **Retry Test**: Simulate a transient connection error (mock logic or strict timeout) and verify retries occur.

### Demo UI (Postponed)
*   Once the above stability fixes are verified, we will proceed with the Gradio UI as originally planned, but built on this more stable foundation. 
