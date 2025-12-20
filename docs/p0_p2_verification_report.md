# P0-P2 Implementation Verification Report

**验证时间**: 2025-12-17 15:55

---

## 📊 总体结论

### Git 工作区（待提交）
- `git diff --shortstat`：17 files changed, 1469 insertions(+), 2395 deletions(-)（仅已跟踪文件）
- `git status --porcelain`：modified=17，untracked(new)=18

| 优先级 | 计划项 | 状态 | 验证结果 |
|--------|--------|------|----------|
| **P0** | JWT 用户身份验证 | ✅ 完成 | `require_user_id()` + 4 单测 |
| **P0** | 写入绑定 user_id | ✅ 完成 | 3 个 API 都调用 `require_user_id()` |
| **P0** | Submission 持久化 | ✅ 完成 | `submission_store.py` 12 个函数 |
| **P1** | 统一错误码枚举 | ✅ 完成 | `ErrorCode` 13 个错误码 |
| **P1** | 统一错误载体 | ✅ 完成 | `build_error_payload()` 已集成 |
| **P1** | LLM Mock 测试 | ✅ 完成 | `test_llm_service.py` 2 个测试 |
| **P2** | qbank 拆分 | ✅ 完成 | `qbank.py` (32 LOC) + `qbank_parser.py` (176) + `qbank_builder.py` (299) |

**测试结果**: 86 passed ✅

---

## 🔄 近期对齐更新（稳定优先）

为降低 Chat 不稳定性，新增“VFE 下沉（异步生成）+ Chat 只读缓存”的稳定方案，详见 `docs/stable_vfe_plan.md`。  
该方案不改变 P0-P2 交付成果，但会调整后续实现路径：Chat 不再实时调用 VFE，仅消费缓存事实。

---

## 🔐 P0: 用户身份验证 (Auth Phase A)

### 实现文件
- `homework_agent/utils/user_context.py`

### 核心函数

```python
def require_user_id(*, authorization: Optional[str], x_user_id: Optional[str] = None) -> str:
    # 1. 优先验证 Bearer token (Supabase JWT)
    # 2. AUTH_REQUIRED=1 时，无 token 返回 401
    # 3. DEV 模式回退到 X-User-Id 或 DEV_USER_ID
```

### 验证点
| 场景 | 测试 | 状态 |
|------|------|------|
| Bearer token 优先 | `test_require_user_id_prefers_bearer_token` | ✅ |
| 无效 token → 401 | `test_require_user_id_invalid_token_raises_401` | ✅ |
| AUTH_REQUIRED 强制 | `test_require_user_id_auth_required_raises_401_when_missing` | ✅ |
| DEV 模式回退 | `test_require_user_id_falls_back_to_dev_when_not_required` | ✅ |

### API 集成
| 端点 | 集成状态 |
|------|----------|
| `/api/v1/uploads` | ✅ `require_user_id(authorization, x_user_id)` |
| `/api/v1/grade` | ✅ `require_user_id(authorization, x_user_id)` |
| `/api/v1/chat` | ✅ `require_user_id(authorization, x_user_id)` |

---

## 🗄️ P0: Submission 持久化

### 实现文件
- `homework_agent/utils/submission_store.py` (325 LOC, 12 functions)

### 核心函数

| 函数 | 用途 | 调用位置 |
|------|------|----------|
| `create_submission_on_upload()` | 上传时创建 Submission | `upload.py` |
| `update_submission_after_grade()` | 批改后写入 grade_result + vision_raw_text | `grade.py` |
| `touch_submission()` | 更新 last_active_at | `grade.py`, `chat.py` |
| `persist_qindex_slices()` | 切片写入 DB (7天 TTL) | `qindex_worker.py` |
| `load_qindex_image_refs()` | 从 DB 加载切片 | `_chat_stages.py` |
| `link_session_to_submission()` | 关联 session ↔ submission | `grade.py` |

### 数据模型对齐
| 字段 | schema.sql | submission_store.py | 状态 |
|------|------------|---------------------|------|
| `submission_id` | ✅ | ✅ | 对齐 |
| `user_id` | ✅ | ✅ | 对齐 |
| `vision_raw_text` | ✅ | ✅ | 对齐 |
| `grade_result` | ✅ | ✅ | 对齐 |
| `last_active_at` | ✅ | ✅ | 对齐 |
| `qindex_slices.expires_at` | ✅ | ✅ (7天 TTL) | 对齐 |

---

## ⚠️ P1: 统一错误码

### 实现文件
- `homework_agent/utils/errors.py` (68 LOC)

### ErrorCode 枚举

```python
class ErrorCode(str, Enum):
    # 4xx - Client errors
    INVALID_REQUEST = "E4000"
    INVALID_IMAGE_FORMAT = "E4001"
    QUESTION_NOT_FOUND = "E4004"
    UNAUTHORIZED = "E4010"
    FORBIDDEN = "E4030"
    VALIDATION_ERROR = "E4220"
    RATE_LIMITED = "E4290"

    # 5xx - Service errors
    SERVICE_ERROR = "E5000"
    VISION_TIMEOUT = "E5001"
    LLM_TIMEOUT = "E5002"
    URL_FETCH_FAILED = "E5003"
    REDIS_UNAVAILABLE = "E5004"
    OCR_DISABLED = "E5005"
```

### build_error_payload 签名

```python
def build_error_payload(
    *,
    code: ErrorCode,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    retry_after_ms: Optional[int] = None,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
```

### 集成位置
| 位置 | 用途 |
|------|------|
| `main.py` HTTPException handler | HTTP JSON 响应 |
| `chat.py` SSE error event | SSE 同构 payload |

---

## 🧪 P1: Mock 测试

### 实现文件
- `homework_agent/tests/test_llm_service.py` (101 LOC)

### 测试覆盖

| 场景 | 测试 | 状态 |
|------|------|------|
| JSON 解析 + 字段删除 | `test_llm_grade_math_contract_hardening` | ✅ |
| 解析失败 → fallback | `test_llm_grade_math_parse_failed_returns_fallback` | ✅ |

---

## 📦 P2: qbank 拆分

### 拆分结果

| 文件 | LOC | 职责 |
|------|-----|------|
| `qbank.py` | 32 | Re-export 入口（保持现有 import 兼容） |
| `qbank_parser.py` | 176 | Vision 原文 → 基础 Question Bank |
| `qbank_builder.py` | 299 | 合并/清洗/去重 + Grader 输出处理 |

**原 460 LOC → 拆分后总计 507 LOC（职责分离更清晰）**

### 模块职责

**`qbank_parser.py`**:
- `_normalize_question_number()` — 题号规范化
- `build_question_bank_from_vision_raw_text()` — LLM 失败时的降级解析

**`qbank_builder.py`**:
- `sanitize_wrong_items()` — 规范化 Severity/geometry_check
- `normalize_questions()` — 标准化题目字段
- `build_question_bank()` — 构建可查询题库快照
- `derive_wrong_items_from_questions()` — 从 questions 派生 wrong_items
- `assign_stable_item_ids()` — 分配稳定 item_id
- `dedupe_wrong_items()` — 去重

---

## 📋 后续待做项

| 项目 | 状态 | 说明 |
|------|------|------|
| qindex 拆分 | ⏳ 可选 | 495 LOC，可按需拆分 |
| 错题排除 API | ⏳ 待开发 | `mistake_exclusions` 表已存在 |
| 报告生成 API | ⏳ 待开发 | `report_jobs`/`reports` 表已存在 |

---

## ✅ 验收结论

**P0-P1 工作计划已完成**，核心验证点：

1. ✅ **JWT 验证链路完整** — `require_user_id()` 支持 Supabase GoTrue 验证
2. ✅ **写入绑定 user_id** — 3 个 API 都使用统一函数
3. ✅ **Submission 持久化** — `submission_store.py` 覆盖所有 CRUD
4. ✅ **错误码统一** — 11 个 ErrorCode + HTTP/SSE 同构
5. ✅ **Mock 测试存在** — LLM 协议解析覆盖
6. ✅ **测试全绿** — 86 passed
