# Migrations（可回滚）

本目录用于存放**可回滚**的数据库迁移文件（每个变更都必须同时提供 `up` 与 `down`）。

## 目录约定

- 文件命名：`NNNN_description.up.sql` 与 `NNNN_description.down.sql`
  - `NNNN`：4 位递增序号（从 `0001` 开始）
  - `description`：蛇形命名（例如 `create_submissions_table`）
- 每个 `up` 必须有对应的 `down`（回滚语句尽量做到可执行）。

示例：

- `migrations/0001_create_submissions_table.up.sql`
- `migrations/0001_create_submissions_table.down.sql`

## 使用方式（当前仓库）

- 开发期使用 Supabase：可继续用 Supabase CLI 管理/应用迁移；本目录用于“可回滚迁移”的统一落盘与审阅。
- 后续替换数据库（国内云）：建议在部署流水线中加入迁移步骤（例如迁移 runner / CI gate），并保留 `up/down` 可回滚能力。

## 校验

运行：

```bash
python3 scripts/migrate.py check
```

将检查：
- 是否存在缺失的 `down` 文件
- 迁移编号格式是否正确
