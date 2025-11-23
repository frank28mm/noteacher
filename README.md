# 作业检查大师 - Supabase 连接说明

本项目将集成 Supabase 以进行数据存储与访问。请按以下步骤完成连接：

## 1. 安装依赖

已安装：`@supabase/supabase-js` 与 `dotenv`。

## 2. 配置环境变量

- 将仓库根目录下的 `.env.example` 复制为 `.env.local`
- 在 `.env.local` 中填写你的 Supabase 项目配置：

```
SUPABASE_URL=你的项目 URL
SUPABASE_ANON_KEY=你的匿名密钥
```

获取方式：登录 Supabase 项目后台 → `Project Settings` → `API` → 复制 `Project URL` 与 `anon public` Key。

注意：
- 请不要将真实密钥提交到版本库，`.env.local` 应保持本地使用。
- `anon` 密钥适合前端/受限访问；服务器端需要更高权限时使用 `service_role`（仅服务端使用，切勿暴露到客户端）。

## 3. 初始化客户端与测试连接

我们将提供 `src/supabaseClient.js` 初始化模块与测试脚本：

- 初始化模块会从 `.env.local` 读取 `SUPABASE_URL` 和 `SUPABASE_ANON_KEY`，创建 Supabase 客户端。
- 测试脚本会验证能否成功调用 Supabase（例如读取认证配置或简单查询）。

完成上述文件后，你可以运行：

```
npm run test:supabase
```

若出现环境变量缺失或密钥错误，请检查 `.env.local` 是否正确填写与保存。

