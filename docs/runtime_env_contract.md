# 运行环境约定与上线清单（真源）

> 目的：统一 dev/test/prod 的运行约定与上线依赖，避免“本地能跑/CI 不能跑/线上不稳”的环境漂移。
> 本文为**单一真源**；其他文档只做入口引用，不重复细节。

## 1) 环境约定表（dev / test / prod）

| 环境 | 核心约定 | 依赖要求 | 错误返回 |
|---|---|---|---|
| dev | 允许降级，优先本地可用 | 外部依赖可缺失（Redis/Supabase/ARK/Silicon） | 允许返回 detail 便于调试 |
| test | **APP_ENV=test**；关闭自动 dotenv | 不要求外部依赖；AUTH_REQUIRED=0；REQUIRE_REDIS=0；LOAD_DOTENV_ON_IMPORT=0 | 禁止泄露敏感信息 |
| prod | 强校验 + 强约束 | 必须提供 SUPABASE_URL/KEY/REDIS_URL/ARK_API_KEY/SILICON_API_KEY；AUTH_REQUIRED=1；CORS 显式白名单 | 统一返回标准错误码 + request_id |

补充约束：
- Worker 在生产建议强制 service role（`WORKER_REQUIRE_SERVICE_ROLE=1`）。
- 生产上线前必须执行 RLS 收紧脚本：优先使用 `supabase/harden_rls_complete.sql`（覆盖 facts/report_jobs 等 dev-time anon 策略）；`supabase/harden_rls_production.sql` 仅覆盖 feedback_messages。
- 测试环境不加载 `.env`，避免污染 CI 与本地回归结果。
- 上传约束（产品/运维一致口径）：单张图片最大 `MAX_UPLOAD_IMAGE_BYTES`（默认 5MB）；客户端建议一次最多上传 4 张。

## 2) 路线 B 上线清单（核心依赖/开关）

### 2.1 Redis 是否必须
- **生产**：必须（建议 `REQUIRE_REDIS=1`）。  
  - `/grade` 异步与 `qindex/grade/report` worker 依赖 Redis 队列。  
  - 若未配置 Redis，生产将无法稳定承载并发与长连接。

### 2.2 Supabase DB 直连（`SUPABASE_DB_URL`）
- **仅在执行 DDL/迁移/补丁时需要**。  
  - 常规运行只需要 `SUPABASE_URL` + `SUPABASE_KEY`（或 `SUPABASE_SERVICE_ROLE_KEY`）。
- 生产变更需按顺序执行：
  1) `migrations/*.up.sql`  
  2) `supabase/patches/*.sql`
  3) 上线前执行 `supabase/harden_rls_complete.sql`

### 2.3 Worker 必备 Key
- **必需**：
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`（生产强制）
  - `REDIS_URL`
  - `ARK_API_KEY`（Doubao）
  - `SILICON_API_KEY`（Qwen3）
- **可选**：
  - SMS 相关（仅启用短信登录时）：`ALIYUN_ACCESS_KEY_ID/SECRET/...`

### 2.4 错误返回策略（生产）
- 对外统一使用标准错误码（`E4xxx/E5xxx`）+ `request_id`。  
- **禁止返回内部异常字符串**（尤其 `/uploads`、`/chat` SSE）。
