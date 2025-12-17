# Homework Agent 代码库评估报告

**评估时间**: 2025-12-17  
**评估范围**: `homework_agent/` 目录下所有 Python 代码

---

## 📊 总体指标

| 指标 | 数值 | 评价 |
|------|------|------|
| 总代码行数 (LOC) | ~11,918 | 中型项目 |
| Python 文件数 | 51 | 模块化良好 |
| 测试文件数 | 15 | ✅ 已提升（含 conftest/spec） |
| 测试用例数 | 86 | ✅ 已达标 |
| 函数总数 | ~244 | 合理 |
| 异步函数数 | ~36 | 符合 FastAPI 模式 |
| API 端点数 | 6 | 精简 |
| Pydantic 模型数 | ~21 | 结构化良好 |

---

## 🏗️ 架构评估

### 模块结构 (Score: 8/10)

```
homework_agent/
├── api/           # API 路由层 (grade, chat, upload, session)
│   ├── _chat_stages.py      # ✅ 新拆分
│   └── _grading_stages.py   # ✅ 新拆分
├── core/          # 领域逻辑 (qbank, qindex, prompts, slice_policy)
├── models/        # Pydantic schemas
├── services/      # 外部服务客户端 (llm, vision, ocr_*)
├── utils/         # 工具函数 (settings, cache, observability)
├── workers/       # 后台任务 (qindex_worker)
└── tests/         # 测试套件
```

**优点**:
- 清晰的分层架构 (API → Core → Services → Utils)
- 依赖方向正确 (上层依赖下层，无循环依赖)
- 新拆分的 `_*_stages.py` 有效降低了主文件复杂度

**改进建议**:
- `core/qindex.py` (495 LOC) 略大，可考虑进一步拆分
- `demo_ui.py` (903 LOC) 作为演示 UI 可独立为 `demo/` 子目录
- API 版本前缀：后端已统一挂载在 `/api/v1/*`（FastAPI `include_router(..., prefix="/api/v1")`）；建议所有客户端/文档/脚本统一使用该前缀，并预留未来 `/api/v2` 兼容升级路径

---

## 📁 文件规模分析

### 最大文件 Top 10

| 文件 | 行数 | 复杂度 | 建议 |
|------|------|--------|------|
| `api/chat.py` | 1,289 | 高 | ✅ 主函数已重构 |
| `api/grade.py` | 906 | 高 | ✅ 主函数已重构 |
| `demo_ui.py` | 903 | 中 | 可拆分 |
| `services/llm.py` | 681 | 中 | 正常 |
| `api/_chat_stages.py` | 647 | 中 | 新模块，正常 |
| `api/_grading_stages.py` | 596 | 中 | 新模块，正常 |
| `core/qindex.py` | 495 | 中 | 可考虑拆分 |
| `services/qindex_locator_siliconflow.py` | 475 | 中 | 正常 |
| `services/ocr_baidu.py` | 419 | 中 | 正常 |
| `tests/test_grading_stages.py` | 411 | 低 | 正常 (测试文件) |
| `utils/submission_store.py` | 324 | 中 | 正常 |

---

## 🧪 测试覆盖评估 (Score: 6/10)

### 测试分布

| 测试文件 | 覆盖模块 | 用例数 |
|----------|----------|--------|
| `test_grading_stages.py` | grade.py, _grading_stages.py | ~15 |
| `test_chat_helpers.py` | chat.py 辅助函数 | ~10 |
| `test_chat_sse_contract.py` | SSE 行为契约 | ~5 |
| `test_grade_utils.py` | grade.py 工具函数 | ~10 |
| `test_session_utils.py` | session.py | ~10 |
| `test_url_image_helpers.py` | url_image_helpers.py | ~10 |
| `test_routes.py` | API 路由 | ~5 |
| `test_qindex_productization.py` | qindex 集成 | ~5 |
| `test_llm_service.py` | services/llm.py | ~2 |
| `spec_*.py` | 行为规范 | ~10 |

**优点**:
- ✅ 关键路径有金丝雀测试 (`test_chat_fail_closed_when_visual_required`)
- ✅ 新增了重构阶段函数的单元测试
- ✅ 测试数量从 62 → 86 (+24)

**改进建议**:
- ❌ `services/vision.py` 无直接单元测试
- ❌ `core/qindex.py` 测试覆盖不足
- 建议: 补充 mock 外部服务的单元测试，目标 100+ tests

---

## ⚠️ 异常处理评估 (Score: 5/10)

### 统计

| 模式 | 数量 | 评价 |
|------|------|------|
| `except Exception` 总数 | 123 | ⚠️ 偏多 |
| `except Exception: pass` | 0 | ✅ 已清理 |
| 结构化日志 (`log_event`) | ⚠️ 口径待统一（建议以业务代码为准统计） | ✅ 良好 |
| 标准日志 (`logger.*`) | 46 处 | 正常 |

**优点**:
- ✅ 所有 `except Exception: pass` 已替换为 `logger.debug()`
- ✅ 关键路径使用 `log_event()` 结构化日志

**改进建议**:
- 123 处 `except Exception` 中，部分可细化为具体异常类型
- OCR 服务层 (`ocr_siliconflow.py`, `ocr_baidu.py`) 的异常处理需要区分:
  - **关键失败** → `warning` + 明确错误返回
  - **Best-effort** → `debug`
- 建议建立统一错误码枚举 + 统一错误载体（JSON 与 SSE 同构），避免“一个接口一种错误形态”导致前端难以处理：

```python
from enum import Enum
from typing import Any, Optional

class ErrorCode(str, Enum):
    # 4xx - Client errors
    INVALID_IMAGE_FORMAT = "E4001"  # 图片格式不支持
    QUESTION_NOT_FOUND = "E4004"    # 题号未找到
    SESSION_EXPIRED = "E4010"       # 会话过期

    # 5xx - Service errors
    VISION_TIMEOUT = "E5001"        # 视觉模型超时
    LLM_TIMEOUT = "E5002"           # LLM 超时
    URL_FETCH_FAILED = "E5003"      # 图片 URL 拉取失败
    REDIS_UNAVAILABLE = "E5004"     # Redis 不可用
    OCR_DISABLED = "E5005"          # OCR/OCR定位未配置

class ErrorPayload(dict):
    # 建议字段：code/message/details/retry_after_ms/request_id/session_id
    pass
```

---

## 🔧 代码质量评估

### 命名规范 (Score: 9/10)
- ✅ 函数/变量使用 `snake_case`
- ✅ 类使用 `PascalCase`
- ✅ 私有函数使用 `_prefix`
- ⚠️ 部分函数名较长 (`_abort_llm_stage_with_vision_only_bank`)

### 类型注解 (Score: 8/10)
- ✅ Pydantic 模型完整使用类型注解
- ✅ 函数签名普遍有返回类型
- ⚠️ 部分 `Dict[str, Any]` 可细化为 TypedDict

### 文档注释 (Score: 7/10)
- ✅ 主要类/函数有 docstring
- ✅ README.md 完整
- ⚠️ 部分辅助函数缺少注释
- ⚠️ 无 API 文档自动生成 (如 Swagger 描述)

### 代码重复 (Score: 7/10)
- ⚠️ `_run_grading_llm_stage` 中 MATH/ENGLISH 分支有部分重复逻辑
- ⚠️ `ocr_siliconflow.py` 与 `qindex_locator_siliconflow.py` 有相似的 API 调用模式

---

## 🔒 安全性评估 (Score: 8/10)

**优点**:
- ✅ API Key 通过环境变量配置 (`pydantic_settings`)
- ✅ 输入校验使用 Pydantic Field validators
- ✅ URL 输入有 Guardrail (过滤 localhost/127.*)
- ✅ Base64 输入有大小限制 (20MB)

**改进建议**:
- ⚠️ `X-User-Id` header 开发模式下可被伪造 (已知 TODO)
- ⚠️ 无 Rate Limiting 实现 (依赖上游 API 限速)
- ✅ 建议将“可信 user_id 来源”列为上线前 P0：使用 Supabase Auth JWT（`Authorization: Bearer <jwt>`）校验并以 `jwt.sub` 作为唯一 user_id；开发期可保留 `X-User-Id` 但必须 gated（如 `DEV_MODE=1`），并禁止生产环境使用

---

## 📈 可观测性评估 (Score: 8/10)

**优点**:
- ✅ 结构化日志 (`log_event`) 包含 correlation IDs (`request_id`, `session_id`)
- ✅ Timing 统计 (`timings_ms`) 嵌入响应
- ✅ 进度追踪 (`save_grade_progress`) 支持前端轮询

**改进建议**:
- ❌ 无 OpenTelemetry/Prometheus 指标导出
- ❌ 无分布式追踪 (Tracing)

---

## 🚀 性能评估 (Score: 7/10)

**优点**:
- ✅ 并发控制 (`asyncio.Semaphore`) 防止线程堆积
- ✅ LRU 缓存 (`@lru_cache`) 用于 Settings
- ✅ SSE 流式输出避免阻塞

**改进建议**:
- ⚠️ Vision/LLM 阻塞调用使用 `asyncio.to_thread()` 而非原生 async
- ⚠️ 无连接池管理 (httpx 默认连接池)
- ⚠️ Redis 缓存无 TTL 自动清理策略 (仅手动 180-day 清理)

---

## 📋 技术债务清单

| 优先级 | 项目 | 影响 | 建议 |
|--------|------|------|------|
| P0 | 可信用户身份（JWT 校验 + 写入绑定 user_id） | 数据隔离/安全 | 分两阶段：A) 后端先验 JWT + 绑定写入；B) 前端再接入登录/注册 UI |
| P1 | 统一错误码与错误载体（HTTP JSON + SSE 同构） | 前端一致性/可观测性 | 统一 `ErrorCode` + `ErrorPayload`，并规范 `retry_after_ms`/correlation id |
| P1 | 123 处 `except Exception` 需细化 | 可观测性 | 按模块逐步清理 |
| P2 | `core/qindex.py` ~495 LOC | 可维护性 | 按职责拆分（locator/slicer/cache） |
| P2 | `services/vision.py` 无单测 | 测试覆盖 | 添加 mock 测试 |
| P3 | API 文档不完整 | 开发体验 | 添加 Swagger descriptions |
| P3 | 无分布式追踪 | 可观测性 | 接入 OpenTelemetry |

---

## ✅ 总体评分

| 维度 | 分数 | 说明 |
|------|------|------|
| 架构设计 | 8/10 | 分层清晰，依赖合理 |
| 代码质量 | 7.5/10 | 命名规范，类型完整，部分重复 |
| 测试覆盖 | 6/10 | 关键路径有覆盖，服务层不足 |
| 异常处理 | 5/10 | 已消除 silent failure，但需细化 |
| 安全性 | 8/10 | 输入校验完善，认证待完善 |
| 可观测性 | 8/10 | 结构化日志良好，缺少 metrics |
| 性能 | 7/10 | 并发控制到位，可优化 async |
| 文档 | 7/10 | README 完整，API 文档不足 |

**综合评分: 7.1/10** — 中等偏上，适合持续迭代的业务系统

---

## 🎯 下一步建议

1. **短期 (1-2 周)**:
   - P0 阶段 A：后端校验 JWT 并让所有写入强制绑定 user_id（允许用“后端签发测试 token”先跑通链路，前端 Auth UI 后续再接）
   - 建立统一错误码枚举 + 统一错误载体（HTTP JSON 与 SSE 同构）
   - 清理 OCR/Locator 层的 `except Exception`
   - 补充 `services/vision.py` 的单元测试

2. **中期 (1 个月)**:
   - P0 阶段 B：前端接入 Supabase Auth UI（登录/注册），替换测试 token
   - 拆分 `core/qindex.py`
   - 添加 OpenAPI 文档描述

3. **长期**:
   - 接入 OpenTelemetry
   - 实现 Rate Limiting
   - 迁移到原生 async 客户端
