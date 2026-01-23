# Supabase 到国内云环境迁移指南

> **目标**：将当前基于 Supabase 的后端架构，平滑迁移到国内云厂商（如火山引擎/阿里云/腾讯云），以满足合规与网络延迟要求。

## 1. 架构映射 (Mapping)

Supabase 不是黑盒，它是开源组件的组合。迁移本质上是**组件替换**。

| 组件 | 当前 (Supabase) | 目标 (国内云：火山/阿里) | 迁移难度 |
|---|---|---|---|
| **数据库** | Supabase Postgres (基于 AWS) | **RDS for PostgreSQL** (14+) | 🟢 低 (标准 PG 协议) |
| **文件存储** | Supabase Storage (S3 协议) | **TOS (火山) / OSS (阿里)** | 🟡 中 (需改少量代码) |
| **认证** | Supabase Auth (GoTrue) | **自研 Local Auth** (Python JWT) | 🟢 已就绪 (AUTH_MODE=local) |
| **管理后台** | Supabase Dashboard (Table Editor) | **Admin UI** (自研) + **DBeaver** | 🟡 中 (需习惯变更) |
| **API 网关** | PostgREST (自动生成 API) | **FastAPI** (Python 业务逻辑) | 🟢 无需迁移 (我们已用 FastAPI) |

---

## 2. 迁移步骤 (Step-by-Step)

### 第一步：数据库迁移 (Database)

这是核心资产。由于我们使用了标准的 SQL 和 RLS，RDS 完美兼容。

1.  **导出数据 (Dump)**
    ```bash
    # 使用 pg_dump 导出结构和数据
    pg_dump "postgresql://postgres:password@db.supabase.co:5432/postgres" \
      --clean --if-exists --quote-all-identifiers \
      --exclude-schema=auth --exclude-schema=storage \
      > dump_full.sql
    ```
    > 注意：排除 `auth` 和 `storage` schema，因为这些是 Supabase 内部结构，我们迁移后只关心 `public` schema。

2.  **创建 RDS 实例**
    *   购买 RDS for PostgreSQL 14+。
    *   创建数据库 `homework_db` 和用户 `homework_user`。
    *   **关键配置**：确保安装 `uuid-ossp` 和 `pg_trgm` 插件（在 RDS 控制台或 SQL 执行 `CREATE EXTENSION`）。

3.  **导入数据 (Restore)**
    ```bash
    psql "postgresql://homework_user:pwd@rds.volces.com:5432/homework_db" < dump_full.sql
    ```

4.  **配置切换**
    *   修改后端 `.env`：
        ```bash
        # 旧
        # SUPABASE_URL=...
        # SUPABASE_KEY=...
        
        # 新 (使用 SQLAlchemy/AsyncPG 直连)
        DATABASE_URL=postgresql://user:pwd@rds.endpoint:5432/db
        ```

### 第二步：文件存储迁移 (Storage)

1.  **数据搬迁**
    *   使用 `rclone` 工具，配置 Supabase S3 端点和 TOS S3 端点，执行 sync。
    *   或者写一个简单的 Python 脚本：`ListObjects` (Supabase) -> `Download` -> `Upload` (TOS)。

2.  **代码适配**
    *   当前代码使用了 `supabase-py` 的 storage client。
    *   迁移后，建议在 `homework_agent/utils/storage.py` 中封装一层抽象，底层改用 `boto3` (AWS SDK，兼容 TOS/OSS) 或云厂商原生 SDK。
    *   **改动点**：`upload_file`, `get_public_url`, `create_signed_url`。

### 第三步：认证切换 (Auth)

我们已经实现了 `AUTH_MODE=local`，这部分最简单。

1.  **切换配置**：设置 `AUTH_MODE=local`。
2.  **数据清洗**：
    *   如果之前有些用户只在 Supabase `auth.users` 而不在 `public.users`，需要写脚本把它们同步过来（主要是 user_id 和 phone）。
    *   密码/Hash：如果是手机号验证码登录，不需要迁移密码 Hash。

### 第四步：管理与运维

迁移后，你将失去 Supabase 的 Web 控制台。管理方式变为：

1.  **数据管理**：使用 **Navicat** 或 **DBeaver** 连接 RDS。这是最专业的做法。
2.  **业务管理**：使用我们即将开发的 **Admin UI** (查看用户、充值、退款)。
3.  **日志/监控**：使用云厂商的“日志服务 (TLS/SLS)”和“云监控”。

---

## 3. 风险控制

1.  **RLS 兼容性**：RDS 支持 RLS，但默认可能是关闭的。导入 SQL 后需检查 `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` 是否生效。
2.  **PostgREST 依赖**：如果我们代码里有直接依赖 PostgREST 的 HTTP 调用（例如 `supabase.table('...').select(...)`），这些代码需要改为 **SQLAlchemy/ORM** 调用，或者自行部署一个 PostgREST 服务容器（PostgREST 是开源的，可以对接任意 PG）。
    *   *现状检查*：我们的代码大量使用了 `supabase-py` client。
    *   *建议*：短期内，为了不重写所有 DB 操作代码，可以考虑**自部署 Supabase 全家桶**（Docker 部署），或者**优先保留 Supabase client 风格但底层换成 PostgREST 容器 + RDS**。
    *   *长期建议*：逐步将 `supabase.table()...` 重构为标准的 Python ORM (SQLAlchemy/Tortoise)，彻底解耦。

## 4. 总结

迁移完全可行。
- **数据**：pg_dump/restore。
- **代码**：主要工作量在于**将 Supabase Client 替换为标准 DB/Storage Client**。
- **管理**：Admin UI + SQL 客户端。
