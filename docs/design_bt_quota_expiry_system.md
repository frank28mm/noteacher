# 额度过期检测 CronJob 设计文档

## 1. 背景

- **商业模式变更**：从订阅模式改为卡密兑换模式
- **新规则**：用户通过兑换卡密获得 BT 额度，额度有 **30 天使用期限**
- **问题**：当前 `user_wallets` 表只记录总额度，无法追踪每笔额度的过期时间

## 2. 方案设计

### 2.1 数据库变更

#### 创建新表 `bt_grants`（额度授予记录表）

```sql
-- migrations/0014_create_bt_grants_table.up.sql

create table if not exists public.bt_grants (
  id uuid primary key default uuid_generate_v4(),
  user_id text not null,
  bt_amount int not null,
  grant_type text not null,              -- 'trial' | 'subscription' | 'addon'
  expires_at timestamptz not null,       -- 额度过期时间
  is_expired boolean not null default false,
  processed_at timestamptz,              -- CronJob 处理时间
  created_at timestamptz not null default now(),
  created_from text,                     -- 来源：'redeem_card' | 'admin_grant' | 'trial_pack'
  reference_id text,                     -- 关联ID：redeem_cards.id 或 admin_audit_logs.id
  meta jsonb not null default '{}'::jsonb
);

-- 索引
create index if not exists idx_bt_grants_user_expires on public.bt_grants (user_id, expires_at);
create index if not exists idx_bt_grants_expires_unexpired on public.bt_grants (expires_at) where is_expired = false;
create index if not exists idx_bt_grants_created on public.bt_grants (created_at desc);
```

#### 修改 `user_wallets` 表（增加过期统计字段）

```sql
-- migrations/0015_add_wallet_expiry_fields.up.sql

-- 添加额度过期统计字段
alter table public.user_wallets
  add column if not exists bt_subscription_active bigint not null default 0,
  add column if not exists bt_subscription_expired bigint not null default 0;

-- 添加最后过期检测时间
alter table public.user_wallets
  add column if not exists last_expiry_check_at timestamptz;
```

### 2.2 兑换流程变更

修改 `quota_service.py` 中的 `grant_subscription_quota` 函数：

1. 发放额度时，同时写入 `bt_grants` 表
2. 计算 `expires_at = now() + 30 days`
3. 同时更新 `user_wallets.bt_subscription_active`（累计未过期额度）

```python
# 新增逻辑
expires_at = datetime.now(timezone.utc) + timedelta(days=30)

# 1. 写入 bt_grants 表
_safe_table("bt_grants").insert({
    "user_id": uid,
    "bt_amount": int(bt_amount),
    "grant_type": "subscription",  # 或 "addon" / "trial"
    "expires_at": expires_at.isoformat(),
    "created_from": "redeem_card",
    "reference_id": redeem_card_id,
}).execute()

# 2. 更新 wallet
_safe_table("user_wallets").update({
    "bt_subscription": existing_total + bt_amount,
    "bt_subscription_active": existing_active + bt_amount,
    "updated_at": now,
}).eq("user_id", uid).execute()
```

### 2.3 CronJob 实现

#### 文件：`homework_agent/workers/expiry_worker.py`

```python
"""
BT 额度过期检测 Worker

运行方式：
1. K8s CronJob（推荐）：每日 02:00 运行
2. 或手动运行：python -m homework_agent.workers.expiry_worker

功能：
1. 扫描 bt_grants 表中过期且未处理的记录
2. 从 user_wallets.bt_subscription_active 中扣除过期额度
3. 标记 bt_grants.is_expired = true
4. 记录操作到 usage_ledger
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from homework_agent.utils.supabase_client import get_worker_storage_client
from homework_agent.utils.observability import log_event

logger = logging.getLogger(__name__)


def _safe_table(name: str):
    storage = get_worker_storage_client()
    return storage.client.table(name)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def find_expired_grants(*, limit: int = 1000) -> List[Dict[str, Any]]:
    """
    查找过期且未处理的额度记录

    Args:
        limit: 单次查询的最大记录数（避免内存溢出）

    Returns:
        过期额度记录列表
    """
    now = _utc_now().isoformat()

    resp = (
        _safe_table("bt_grants")
        .select("*")
        .lt("expires_at", now)
        .eq("is_expired", False)
        .order("expires_at", asc=True)
        .limit(limit)
        .execute()
    )

    return getattr(resp, "data", [])


def process_expired_grant(grant: Dict[str, Any]) -> bool:
    """
    处理单笔过期额度

    Returns:
        是否处理成功
    """
    user_id = grant.get("user_id")
    grant_id = grant.get("id")
    bt_amount = int(grant.get("bt_amount", 0))

    if not user_id or not grant_id:
        return False

    try:
        # 1. 更新 user_wallets（扣除 active 额度，增加 expired 统计）
        now = _utc_now().isoformat()

        wallet_resp = (
            _safe_table("user_wallets")
            .select("*")
            .eq("user_id", user_id)
            .single()
            .execute()
        )

        wallet = getattr(wallet_resp, "data", None)
        if not wallet:
            logger.warning(f"Wallet not found for user {user_id}")
            return False

        current_active = int(wallet.get("bt_subscription_active", 0))
        current_expired = int(wallet.get("bt_subscription_expired", 0))

        # 确保 active 不会变成负数
        new_active = max(0, current_active - bt_amount)
        new_expired = current_expired + bt_amount

        (
            _safe_table("user_wallets")
            .update({
                "bt_subscription_active": new_active,
                "bt_subscription_expired": new_expired,
                "last_expiry_check_at": now,
                "updated_at": now,
            })
            .eq("user_id", user_id)
            .execute()
        )

        # 2. 标记 bt_grants 为已处理
        (
            _safe_table("bt_grants")
            .update({
                "is_expired": True,
                "processed_at": now,
            })
            .eq("id", grant_id)
            .execute()
        )

        # 3. 记录到 usage_ledger
        ledger_payload = {
            "user_id": user_id,
            "endpoint": "expiry_worker",
            "stage": "expire",
            "bt_delta": -bt_amount,
            "bt_subscription_delta": -bt_amount,
            "meta": {
                "grant_id": grant_id,
                "grant_type": grant.get("grant_type"),
                "created_from": grant.get("created_from"),
                "reference_id": grant.get("reference_id"),
                "expires_at": grant.get("expires_at"),
                "reason": "bt_quota_expired_after_30_days",
            },
        }

        try:
            _safe_table("usage_ledger").insert(ledger_payload).execute()
        except Exception as e:
            logger.warning(f"Failed to write ledger for {user_id}: {e}")

        log_event(
            logger,
            "bt_grant_expired",
            user_id=user_id,
            grant_id=grant_id,
            bt_amount=bt_amount,
            new_active=new_active,
            new_expired=new_expired,
        )

        return True

    except Exception as e:
        logger.exception(f"Failed to process expired grant {grant_id}: {e}")
        return False


def run_expiry_check(*, batch_size: int = 1000, max_batches: int = 100) -> Dict[str, int]:
    """
    运行额度过期检测主流程

    Args:
        batch_size: 每批处理的记录数
        max_batches: 最大批次数（防止死循环）

    Returns:
        统计信息
    """
    stats = {
        "total_processed": 0,
        "total_expired": 0,
        "total_failed": 0,
        "batches_processed": 0,
    }

    log_event(logger, "expiry_check_started")

    while stats["batches_processed"] < max_batches:
        expired_grants = find_expired_grants(limit=batch_size)

        if not expired_grants:
            break

        stats["batches_processed"] += 1

        for grant in expired_grants:
            stats["total_processed"] += 1

            if process_expired_grant(grant):
                stats["total_expired"] += int(grant.get("bt_amount", 0))
            else:
                stats["total_failed"] += 1

        # 如果返回数量少于 batch_size，说明已经处理完
        if len(expired_grants) < batch_size:
            break

    log_event(logger, "expiry_check_completed", **stats)

    return stats


def main():
    """主入口（可独立运行或被 CronJob 调用）"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    stats = run_expiry_check()

    print(f"\n=== BT 额度过期检测完成 ===")
    print(f"处理记录数: {stats['total_processed']}")
    print(f"过期额度: {stats['total_expired']} BT")
    print(f"失败数: {stats['total_failed']}")
    print(f"批次: {stats['batches_processed']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### 2.4 K8s CronJob YAML

```yaml
# deploy/k8s/cronjob-expiry-worker.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: expiry-worker
  namespace: homework-agent
spec:
  # 每日 02:00 运行
  schedule: "0 2 * * *"
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
          - name: expiry-worker
            image: registry.cn-hangzhou.aliyuncs.com/YOUR_REPO/homework-agent:latest
            command: ["python", "-m", "homework_agent.workers.expiry_worker"]
            env:
            - name: SUPABASE_URL
              valueFrom:
                configMapKeyRef:
                  name: supabase-config
                  key: url
            - name: SUPABASE_ANON_KEY
              valueFrom:
                secretKeyRef:
                  name: supabase-secret
                  key: anon-key
            - name: SUPABASE_SERVICE_ROLE_KEY
              valueFrom:
                secretKeyRef:
                  name: supabase-secret
                  key: service-role-key
            resources:
              requests:
                cpu: 100m
                memory: 128Mi
              limits:
                cpu: 500m
                memory: 256Mi
```

## 3. 验收标准

1. **数据完整性**：
   - 每笔额度发放都记录到 `bt_grants` 表
   - `bt_subscription_active` 准确反映未过期额度
   - `bt_subscription_expired` 准确反映已过期额度

2. **过期检测**：
   - CronJob 每日正确检测并处理过期额度
   - 过期额度从 `bt_subscription_active` 中扣除
   - 操作记录到 `usage_ledger`

3. **边界情况**：
   - 扣减时 `bt_subscription_active` 不会变成负数
   - 网络中断等异常情况有日志记录
   - 重复执行不会重复扣减（幂等性）

## 4. 后续优化

- [ ] 用户通知：额度即将过期前 3 天发送通知
- [ ] 前端展示：显示额度过期时间和过期历史
- [ ] 批量操作优化：使用 PostgreSQL 批量更新减少网络往返
