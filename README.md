# Homework Checker Agent (作业检查大师)

**Homework Checker Agent** 是一个基于多模态大模型（Vision + LLM）的智能作业批改与辅导系统后端。
它集成了 **SiliconFlow (Qwen3)** 和 **Volcengine Ark (Doubao)** 两大顶尖模型，提供精准的作业批改、错题分析以及苏格拉底式的启发式辅导。

---

## 🌟 核心特性 (Key Features)

### 1. 智能批改 (Smart Grading)
- **双模态支持（Vision 可选）**：
  - **Doubao-Vision（默认 Vision）**：高可用视觉识别；**仅支持公网 URL 输入**。
  - **Qwen3-VL（备用 Vision）**：擅长复杂手写体与几何图形识别；支持 URL 或 Base64（兜底）。
- **深度分析**：输出结构化 JSON，包含分数、错题位置 (bbox)、错误原因及详细解析。
- **鲁棒性设计**：
  - **Fail Fast**: 遇到 RateLimit 立即报错，不盲目重试。
  - **Anti-Jitter**: 网络超时/连接中断自动指数退避重试 (Exponential Backoff)。
  - **Input Guardrails**: 路由层拦截非法输入 (Localhost/超大 Base64)，减少无效 Token 消耗。
  - **上传兼容**: 支持 HEIC/HEIF 自动转 JPEG，PDF 自动拆前 8 页转图片；Qwen3 默认需最小边 ≥28px，Doubao ≥14px。

### 2. 苏格拉底辅导 (Socratic Tutor)
- **启发式引导**：不直接给出答案，通过连续提问引导学生自己发现错误（**默认不限轮、无硬上限**；提示递进按轮次循环）。
- **上下文注入**：基于 `/grade` 生成的 session（即便全对也可聊），进行针对性辅导；不做纯闲聊。
- **推理模型**：当 Chat 走 Ark provider 时，使用 `ARK_REASONING_MODEL` 指定的模型（测试环境可指向 `doubao-seed-1-6-vision-250815`）；`ARK_REASONING_MODEL_THINKING` 非必需。
- **会话管理**：支持 SSE 流式输出、断线续接 (Last-Event-ID) 和会话状态持久化 (InMemory/Redis)。

---

## 🚀 快速开始 (Quick Start)

### 环境准备
- Python 3.10+
- Redis (可选，生产环境推荐)

### 安装与运行
```bash
# 1. 克隆项目
git clone https://github.com/frank28mm/noteacher.git
cd noteacher

# 2. 创建环境
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量 (参考 .env.template)
cp .env.template .env
# 编辑 .env 填入 SILICON_API_KEY, ARK_API_KEY 等

# 4.1 初始化 Supabase 数据表（可选但推荐）
# 在 Supabase 控制台 -> SQL Editor 运行 supabase/schema.sql（含开发期 user_uploads 表等）

# 5. 启动服务（从项目根目录运行）
export PYTHONPATH=$(pwd)
export no_proxy=localhost,127.0.0.1
uvicorn homework_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. 启动 QIndex Worker（可选，但推荐）
用于 **Baidu OCR + 题目 bbox/切片** 的后台生成（避免拖慢主进程），需要 Redis（`REDIS_URL`）：
```bash
python -m homework_agent.workers.qindex_worker
```

> 说明：
> - 依赖安装入口为项目根目录 `requirements.txt`（会包含 `homework_agent/requirements.txt`）。
> - Worker 依赖 Redis：需设置 `REDIS_URL`，并确保 Redis 可连接。

---

## 🛠️ 验证与测试 (Verification)

本项目包含一套完整的验证脚本，用于确保各组件的稳定性。

| 脚本 | 描述 | 关键点 |
|------|------|--------|
| `scripts/e2e_grade_chat.py` | 端到端冒烟 | `/uploads` → `/grade(upload_id)` → `/chat`（SSE） |
| `scripts/verify_qindex_status.py` | qindex/TTL 验证 | `/session/{sid}/qbank` + Redis key/TTL +（可选）自动跑 `/uploads`+`/grade` |
| `scripts/verify_vision_qwen.py` | Vision 直连验证 | 直调 SiliconFlow Qwen3（需配置 key/model） |
| `scripts/verify_vision_ark.py` | Vision 直连验证 | 直调 Ark/Doubao Vision（需配置 key/model） |

运行示例：
```bash
./.venv/bin/pytest -q
```

### 🚀 发布前检查清单 (Pre-release Checklist)

> ⚠️ **重要**：发布前务必完成以下验证！

- [ ] **E2E 冒烟测试**：运行 `python3 scripts/e2e_grade_chat.py` 验证 `/upload→/grade→/chat` 完整链路
- [ ] **Live Inventory 验收**（可选）：`python3 scripts/collect_inventory_live_metrics.py --limit 5` 验证真实样本
- [ ] **CI 全绿**：确认 GitHub Actions 所有 job 通过
- [ ] **SSE 兜底断线（B 方案）**：生产建议设置 `CHAT_IDLE_DISCONNECT_SECONDS=120`，上线后按日志事件 `chat_llm_first_output` 的 p99 回调（如调到 90/120/180）

---

## 📚 API 使用指南

### 0. 后端权威上传（推荐）(`POST /api/v1/uploads`)
前端仅上传原始文件给后端；后端落到 Supabase Storage（用户隔离路径）并返回 `upload_id`（一次上传=一次 Submission）与 `page_image_urls`：

> Dev 阶段用 `X-User-Id` / `DEV_USER_ID` 兜底；上线后替换为真实登录体系（并收紧 RLS）。

### 1. 批改作业 (`POST /api/v1/grade`)
推荐使用 **公网 URL** 图片以获得最佳性能；也支持用 `upload_id` 让后端自行解析图片列表。

```json
{
  "subject": "math",
  "vision_provider": "doubao",
  "images": [
    { "url": "https://example.com/homework.jpg" }
  ]
}
```

使用 `upload_id`（images 为空时由后端反查并补齐）：
```json
{
  "subject": "math",
  "vision_provider": "doubao",
  "upload_id": "upl_xxxxxxxxxxxxxxxx",
  "images": []
}
```

### 2. 开始辅导 (`POST /api/v1/chat`)
支持 SSE 流式响应。

```json
{
  "question": "这道题我哪里错了？",
  "session_id": "optional-session-id",
  "context_item_ids": []
}
```

---

## 🗓️ 开发计划 (Roadmap)

- [x] **Phase 1: Agent Core** (当前状态)
    - [x] FastAPI 基础设施与路由
    - [x] LLM/Vision 双客户端实现
    - [x] 稳定性建设 (Retry, Guardrails)
- [ ] **Phase 2: Gradio Demo UI** (进行中)
    - [ ] 双 Tab 界面：批改 + 辅导
    - [ ] 本地图片上传支持
- [ ] **Phase 3: Asynchronous & Production**
    - [ ] Redis 队列集成
    - [ ] 批处理任务状态管理
    - [ ] Submission 持久化（原始图片/识别原文/批改结果按时间可查）
    - [ ] 对话历史 7 天、切片 7 天、静默 180 天清理策略
    - [ ] 错题排除（只影响统计/报告）+ 异步学业报告（可下载/历史报告）

---

**License**: MIT
