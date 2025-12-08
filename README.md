# Homework Checker Agent (作业检查大师)

**Homework Checker Agent** 是一个基于多模态大模型（Vision + LLM）的智能作业批改与辅导系统后端。
它集成了 **SiliconFlow (Qwen3)** 和 **Volcengine Ark (Doubao)** 两大顶尖模型，提供精准的作业批改、错题分析以及苏格拉底式的启发式辅导。

---

## 🌟 核心特性 (Key Features)

### 1. 智能批改 (Smart Grading)
- **双模态支持**：
  - **Qwen3-VL (主力)**：具备强大的视觉推理能力，擅长复杂手写体和几何图形识别。
  - **Doubao-Vision (备选)**：提供高可用的视觉服务兜底。
- **深度分析**：输出结构化 JSON，包含分数、错题位置 (bbox)、错误原因及详细解析。
- **鲁棒性设计**：
  - **Fail Fast**: 遇到 RateLimit 立即报错，不盲目重试。
  - **Anti-Jitter**: 网络超时/连接中断自动指数退避重试 (Exponential Backoff)。
  - **Input Guardrails**: 路由层拦截非法输入 (Localhost/超大 Base64)，减少无效 Token 消耗。
  - **上传兼容**: 支持 HEIC/HEIF 自动转 JPEG，PDF 自动拆前 8 页转图片；Qwen3 默认需最小边 ≥28px，Doubao ≥14px。

### 2. 苏格拉底辅导 (Socratic Tutor)
- **启发式引导**：不直接给出答案，通过连续提问引导学生自己发现错误（最多 5 轮）。
- **上下文注入**：自动关联 `/grade` 产生的错题记录，进行针对性辅导。
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

# 5. 启动服务
uvicorn homework_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🛠️ 验证与测试 (Verification)

本项目包含一套完整的验证脚本，用于确保各组件的稳定性。

| 脚本 | 描述 | 关键点 |
|------|------|--------|
| `scripts/verify_stability.py` | **核心稳定性测试** | API 防呆、重试逻辑、RateLimit 截断、E2E 冒烟 |
| `scripts/verify_grade_llm.py` | 评分逻辑验证 | 验证 JSON 结构和 Prompt 有效性 |
| `scripts/verify_socratic_tutor.py` | 辅导流程验证 | 模拟 5 轮对话，检查启发式策略 |
| `scripts/verify_vision_qwen.py` | 视觉服务验证 | 测试 SiliconFlow Qwen3 调用 |

运行示例：
```bash
python scripts/verify_stability.py
```

---

## 📚 API 使用指南

### 1. 批改作业 (`POST /api/v1/grade`)
推荐使用 **公网 URL** 图片以获得最佳性能。

```json
{
  "subject": "math",
  "vision_provider": "qwen3",
  "images": [
    { "url": "https://example.com/homework.jpg" }
  ]
}
```

### 2. 开始辅导 (`POST /api/v1/chat`)
支持 SSE 流式响应。

```json
{
  "question": "这道题我哪里错了？",
  "session_id": "optional-session-id",
  "context_item_ids": ["item_index_0"]
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

---

**License**: MIT
