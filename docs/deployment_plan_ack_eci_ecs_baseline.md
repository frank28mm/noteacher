---
title: Deployment Plan (ACK+ECI + ECS Baseline)
owner: frank
status: draft
last_updated: 2026-01-30
---

# 部署方案（一次性落地）：ECS 常驻 + ACK/K8s + ECI 弹性扩容 grade_worker + PolarDB for Supabase

本文把仓库内“真源口径”落成可执行的部署清单。

真源对齐：
- 承载方式/扩缩容策略：`docs/tasks/development_plan_grade_reports_security_20260101.md`（WS-D）
- 运行环境约定（prod 必选项）：`docs/runtime_env_contract.md`
- 架构总览（API + workers + Redis + Supabase）：`system_architecture.md`

## 0. 你要达成的目标（最终态）

一次性部署完成后，你会拥有：

- 稳态（常驻）：至少 1 台 ECS 提供固定算力，承载 API + 常驻 workers。
- 峰值（burst）：`grade_worker` 能在 ACK 上按 Redis 队列深度自动扩容到多 Pod，并可缩回（可配置 scale-to-zero）。
- 数据层：PolarDB for Supabase（兼容 Supabase API：PostgREST/Auth/Storage 等）作为长期数据与对象存储。

关键认知：
- “单台 ECS + Docker 多容器”可以跑稳态，但无法自动“开 pod/自动缩回”。
- 自动扩缩容必须依赖 ACK/K8s（如 KEDA + ECI）。

## 1. 部署拓扑（推荐：单控制面）

推荐把所有工作负载都放到 ACK（同一个集群），只是调度策略不同：

- NodePool（ECS 常驻节点池，1 台 4c16g 起步）：
  - `api`（FastAPI）
  - `qindex_worker` / `facts_worker` / `report_worker` / `review_cards_worker`（常驻小副本）
- Serverless（ECI/虚拟节点）：
  - `grade_worker`（KEDA 驱动，按队列深度扩缩容）

外部依赖（集群外）：
- Redis（建议托管 Redis；也可以 ACK 内 Redis，但生产不建议把队列依赖做成同节点单点）
- PolarDB for Supabase（数据库 + Storage）

## 2. 先决条件清单（阿里云侧）

### 2.1 网络与基础设施

- 1 个 VPC + 交换机（ACK、ECI、Redis、PolarDB for Supabase 都在同 VPC 或可达）
- 出网能力（NAT 网关或等效方案）：
  - 目的：拉镜像、访问外部 LLM/VLM（Ark/SiliconFlow）、访问 PolarDB for Supabase
- 对外入口：CLB/ALB/Ingress（至少把 API 暴露出来）

### 2.2 ACK 集群

- ACK 托管集群（专业版/按小时计费，属于“底座费”）
- ECS 常驻节点池：1 台 4c16g
- 开通 ECI（Serverless）能力，确保 Pod 可调度到 ECI

### 2.3 镜像仓库

- ACR（阿里云容器镜像服务）
  - ACK/ECI 拉镜像稳定性强于公网拉取
  - 建议镜像 tag 使用不可变版本（例如 git sha 或日期+序号）

## 3. 数据库初始化（PolarDB for Supabase）

按 `docs/runtime_env_contract.md` 的“真源顺序”执行（生产/预发一致）：

1) 迁移：`migrations/*.up.sql`
2) 补丁：`supabase/patches/*.sql`
3) 上线前 RLS 收紧：`supabase/harden_rls_complete.sql`

推荐执行方式（两种选一）：

- 方式 A（最直观）：PolarDB for Supabase 控制台 / SQL Editor 按顺序执行。
- 方式 B（自动化）：使用仓库脚本 `scripts/apply_supabase_sql.py`（需要 `SUPABASE_DB_URL` 直连）。

验收（必须做）：
- 匿名策略已收紧（RLS harden 生效）。
- worker 使用 service role key 可正常 UPDATE/INSERT 需要的表（facts/report_jobs 等）。

## 4. 运行期密钥与权限（prod 约束）

来自 `docs/runtime_env_contract.md`：

- API（对外服务）最小必需：
  - `APP_ENV=prod`
  - `AUTH_REQUIRED=1`
  - `ALLOW_ORIGINS`（CORS 白名单）
  - `REDIS_URL`
  - `SUPABASE_URL`
  - `SUPABASE_KEY`（anon key）
  - `ARK_API_KEY`
  - `SILICON_API_KEY`
  - `JWT_SECRET`
  - （建议）`MAX_UPLOAD_IMAGE_BYTES=5242880`（单张图片大小上限；客户端建议一次最多上传 4 张）

- Workers（生产建议强制）：
  - `WORKER_REQUIRE_SERVICE_ROLE=1`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `REDIS_URL`
  - `ARK_API_KEY`
  - `SILICON_API_KEY`
  - （建议）`MAX_UPLOAD_IMAGE_BYTES=5242880`

落地原则：
- service role key 只进 worker 的运行环境（K8s Secret），不要给 API。
- API 使用 anon key + 鉴权/RLS 兜底。

## 5. 容器镜像构建与发布（一次打包，多入口运行）

仓库已有 `Dockerfile`，默认 entrypoint 跑 API：

```bash
docker build -t <acr>/<namespace>/homework-agent:<tag> .
docker push <acr>/<namespace>/homework-agent:<tag>
```

同一个镜像用不同 command 启动不同 worker：
- `python -m homework_agent.workers.grade_worker`
- `python -m homework_agent.workers.qindex_worker`
- `python -m homework_agent.workers.facts_worker`
- `python -m homework_agent.workers.report_worker`
- `python -m homework_agent.workers.review_cards_worker`

## 6. K8s 部署清单（仓库现状 + 你需要补齐的内容）

当前仓库已提供最小可落地的一组 manifests：

- 基础：
  - Namespace：`k8s/namespace.yaml`
  - Service：`k8s/service.yaml`
  - Secret 模板：`k8s/secret.example.yaml`
  - 说明：`k8s/README.md`

- API：
  - `k8s/deployment-api.yaml`
  - （可选）HPA：`k8s/hpa-api.yaml`

- Workers（常驻）：
  - `k8s/worker-qindex.yaml`
  - `k8s/worker-facts.yaml`
  - `k8s/worker-report.yaml`
  - `k8s/worker-review-cards.yaml`

- Workers（弹性）：
  - `k8s/worker-grade.yaml`
  - （可选）KEDA：`k8s/keda-grade-worker.yaml`

说明：
- 生产不要直接 `kubectl apply -f k8s/secret.example.yaml`；应使用外部 Secret Manager 或 CI/CD 注入。
- KEDA 的 Redis scaler 需要 `host:port` 形式地址（本仓库通过 `REDIS_HOST` env 提供），应用运行仍使用 `REDIS_URL`（redis://.../db）。

## 7. 调度策略（确保“稳态在 ECS、弹性在 ECI”）

### 7.1 稳态工作负载（api + 常驻 workers）

目标：这些 Pod 固定跑在 ECS 节点池，副本数小且稳定。

建议：
- `api`：至少 2 副本（滚动升级不中断），后续再加 HPA。
- `qindex/facts/report/review_cards`：各 1 副本起步（必要时 2），不做强弹性。

落地方式（选择其一）：
- nodeSelector/affinity：将这些 Deployment 绑定到 ECS 节点池的 label。
- taint/toleration：给 ECS 节点池一个专用 taint，仅允许稳态组件容忍。

### 7.2 弹性工作负载（grade_worker）

目标：grade_worker 尽量跑在 ECI（不吃常驻 ECS 的 CPU/内存），并通过 KEDA 扩缩容。

真源建议参数（来自 WS-D，可先按默认值落地）：
- `GRADE_WORKER_MAX_INFLIGHT_PER_POD=1`（单 Pod 并发 1）
- KEDA：
  - `minReplicaCount=0..2`（你要“低冷启动”就设 1；想省钱就 0）
  - `maxReplicaCount=50`（先保守上限）
  - `listLength=10`（示例：每积压 10 个 job 扩 1 Pod）
  - `cooldownPeriod=300`

落地方式：
- 给 grade_worker Deployment 加 nodeSelector/affinity，使其优先/仅调度到 ECI。
- KEDA 的触发源绑定 Redis `grade:queue`。

## 8. 部署步骤（按顺序执行）

### 8.1 创建 namespace + secret

```bash
kubectl apply -f k8s/namespace.yaml

# 生产建议使用外部 Secret Manager / CI 注入。
# 非生产临时验证可用：
kubectl apply -f k8s/secret.example.yaml
```

注意：在执行前使用外部 Secret Manager/CI 注入，或基于 `k8s/secret.example.yaml` 生成实际 Secret。

### 8.2 部署 API 与常驻 workers

```bash
kubectl apply -f k8s/deployment-api.yaml
kubectl apply -f k8s/service.yaml

kubectl apply -f k8s/worker-qindex.yaml
kubectl apply -f k8s/worker-facts.yaml
kubectl apply -f k8s/worker-report.yaml
kubectl apply -f k8s/worker-review-cards.yaml
```

### 8.3 部署 grade_worker（先固定 1 副本跑通）

第一步建议先不用 KEDA，先把队列链路跑通：

```bash
kubectl apply -f k8s/worker-grade.yaml
```

### 8.4 启用 autoscaling（HPA + KEDA）

在“跑通 + 观测正常”后再启用：

- API：HPA
- grade_worker：KEDA

前置条件：
- HPA：集群已安装 Metrics Server。
- KEDA：集群已安装 KEDA。

启用后验收：
- 往 `grade:queue` 压任务时，grade_worker 副本数上升。
- 队列清空后，grade_worker 副本数下降（可缩到 0）。

## 9. 上线前验收（必须跑）

### 9.1 健康检查

- API：`/healthz`、`/readyz`
- 确认 readiness 在 Redis 不可用时会失败（避免“假就绪”）

### 9.2 E2E 冒烟

需要真实环境变量与可达的外部依赖：

```bash
python3 scripts/e2e_grade_chat.py
```

### 9.3 安全与配置

- 确认生产环境启用：`AUTH_REQUIRED=1`、CORS 白名单。
- 确认 worker 环境启用：`WORKER_REQUIRE_SERVICE_ROLE=1` 且使用 `SUPABASE_SERVICE_ROLE_KEY`。
- 确认 RLS harden 已执行（至少 `supabase/harden_rls_complete.sql`）。

## 10. 回滚方案（最小可执行）

### 10.1 应用回滚

- 镜像 tag 回滚：把 Deployment 的镜像从 `<tag_new>` 回到 `<tag_old>`。
- 如果你用 `kubectl rollout`：

```bash
kubectl -n homework-agent rollout undo deployment/homework-agent-api
kubectl -n homework-agent rollout undo deployment/homework-agent-grade-worker
```

### 10.2 KEDA/HPA 回滚

- 出现扩容导致上游 429/失败率上升：
  - 先把 KEDA `maxReplicaCount` 降低（例如 5/10）
  - 或临时删除 ScaledObject（恢复固定副本）

## 11. 常见踩坑（按真源提前规避）

- 单机不存在“自动扩容 pod”：要 KEDA 就必须 ACK。
- grade_worker 扩容不等于吞吐就提升：上游（Ark/Silicon）有配额/网络抖动，必须有 `maxReplicaCount` 护栏。
- Secret 管理：示例 `k8s/secret.example.yaml` 不能直接用于生产。
- RLS：不上线前就收紧，避免“调试时能写、上线后写不进去”的权限漂移。
