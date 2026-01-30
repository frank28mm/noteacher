# 兑换卡系统设计 (Redemption System Design)

> **文档类型**: 系统设计文档  
> **功能**: 兑换码生成、分发、兑换与管理  
> **状态**: ✅ 已实现

---

## 1. 概述

兑换卡系统允许通过兑换码（Redeem Code）向用户发放 BT（Brain Token）额度，用于：
- 营销活动（新用户注册奖励、节日促销）
- 线下渠道（实体卡片、合作伙伴）
- 用户补偿（系统故障补偿、客服安抚）

---

## 2. 数据模型

### 2.1 数据库表结构

#### redeem_cards (兑换码表)

| 字段 | 类型 | 说明 |
|------|------|------|
| `card_id` | UUID | 主键，唯一标识 |
| `code` | VARCHAR(32) | 兑换码字符串，唯一索引 |
| `batch_id` | VARCHAR(32) | 批次 ID，用于分组管理 |
| `bt_amount` | INTEGER | 兑换后可获得的 BT 额度 |
| `status` | ENUM | `unused`, `used`, `disabled` |
| `expires_at` | TIMESTAMP | 过期时间 |
| `used_by` | UUID | 使用者的 user_id（外键） |
| `used_at` | TIMESTAMP | 兑换时间 |
| `created_at` | TIMESTAMP | 生成时间 |
| `card_type` | VARCHAR(32) | 卡类型：trial_pack / subscription_pack / report_coupon |
| `premium_days` | INTEGER | 高级功能天数 |
| `plan_tier` | VARCHAR(16) | 套餐等级 |
| `report_coupons` | INTEGER | 报告券数量 |

#### redemptions (兑换记录表)

| 字段 | 类型 | 说明 |
|------|------|------|
| `redemption_id` | UUID | 主键 |
| `user_id` | UUID | 兑换用户 ID |
| `card_id` | UUID | 关联的兑换码 |
| `bt_amount` | INTEGER | 实际获得的 BT 额度 |
| `coupon_amount` | INTEGER | 获得的报告券数量 |
| `redeemed_at` | TIMESTAMP | 兑换时间 |
| `source` | VARCHAR(32) | 来源标识（如 `web`, `app`, `partner_X`） |

---

## 3. 业务流程

### 3.1 兑换码生命周期

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   生成      │ →  │   分发      │ →  │   兑换      │ →  │   核销      │
│  (Admin)    │    │  (Marketing)│    │  (User)     │    │  (System)   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

### 3.2 详细流程

#### 阶段 1: 生成 (Generate)

**触发者**: 管理员

**API**: `POST /admin/redeem_cards/generate`

**流程**:
1. 管理员指定批次参数：
   - `count`: 生成数量（如 1000 张，最大 1000）
   - `bt_amount`: 每张卡的 BT 额度（如 50000）
   - `coupon_amount`: 每张卡的报告券数量（如 3）
   - `card_type`: 卡类型（trial_pack / subscription_pack / report_coupon）
   - `batch_id`: 批次 ID（自定义，如 `NEWYEAR2026`）
   - `expires_days`: 过期天数（默认 30 天）
   - `meta`: 可选元数据（可包含 `target_tier` 指定套餐等级）
2. 系统生成随机兑换码（格式：14 位大写字母+数字，如 `ABC123DEF456G7`）
3. 批量插入 `redeem_cards` 表
4. 返回批次 ID 和生成的卡列表

**兑换码格式示例**:
```
NEWYEAR-ABC123XYZ789
PROMO-QWE456RTY012
GIFT-XXX-YYY-ZZZ
```

#### 阶段 2: 分发 (Distribute)

**触发者**: 运营/市场团队

**分发渠道**:
- **线上**: 邮件、短信、App Push
- **线下**: 实体卡片印刷（刮刮卡）
- **合作**: 渠道商分发（带渠道标识）

#### 阶段 3: 兑换 (Redeem)

**触发者**: 用户

**API**: `POST /subscriptions/redeem`

**流程**:
1. 用户在前端输入兑换码
2. 后端验证兑换码：
   - 格式正确性
   - 存在性
   - 未使用状态
   - 未过期
   - 未被禁用
3. 如验证通过：
   - 开启数据库事务
   - 更新 `redeem_cards.status` → `used`
   - 更新 `redeem_cards.used_by`, `used_at`
   - 插入 `redemptions` 记录
   - 增加用户钱包 BT 额度
   - 提交事务
4. 返回兑换成功信息

**错误处理**:
```json
{
  "error_code": "INVALID_CODE",       // 兑换码不存在
  "error_code": "ALREADY_USED",       // 已被使用
  "error_code": "EXPIRED",            // 已过期
  "error_code": "DISABLED"            // 批次被禁用
}
```

#### 阶段 4: 核销查询 (Query)

**API**: `GET /subscriptions/redemptions`

用户可查看自己的兑换历史。

---

## 4. 管理功能

### 4.1 批次管理

#### 查看批次
**API**: `GET /admin/redeem_cards/batches`

返回批次列表：
```json
{
  "batches": [
    {
      "batch_id": "batch_xxx",
      "prefix": "NEWYEAR-",
      "total_count": 1000,
      "used_count": 350,
      "bt_value": 50,
      "created_at": "2026-01-01T00:00:00Z",
      "expires_at": "2026-02-28T23:59:59Z",
      "status": "active"
    }
  ]
}
```

#### 禁用批次
**API**: `POST /admin/redeem_cards/batches/{batch_id}/disable`

批量禁用某一批次的所有未使用兑换码（用于活动提前结束或发现问题）。

#### 批量更新
**API**: `POST /admin/redeem_cards/bulk_update`

支持批量操作：
- 延长过期时间
- 调整 BT 面值
- 标记特定状态

### 4.2 统计报表

**API**: `GET /admin/redemptions`

查看所有兑换记录，支持筛选：
- 按批次
- 按时间范围
- 按用户
- 按来源渠道

---

## 5. 安全与风控

### 5.1 兑换码安全

- **随机性**: 使用 `secrets.token_urlsafe()` 生成，避免可预测
- **唯一性**: 数据库唯一索引，防止重复
- **格式验证**: 正则校验，防止注入

### 5.2 防刷机制

- **兑换频率限制**: 单用户每分钟最多 5 次尝试
- **IP 限流**: 单 IP 每小时最多 50 次尝试
- **错误次数**: 连续 10 次错误则临时锁定 1 小时

### 5.3 审计要求

- 所有生成操作记录管理员身份
- 所有兑换操作记录用户 ID、IP、时间戳
- 支持导出兑换记录用于财务对账

---

## 6. 集成示例

### 6.1 前端兑换界面

```typescript
// 兑换码输入组件
const RedeemForm = () => {
  const [code, setCode] = useState('');
  
  const handleRedeem = async () => {
    try {
      const res = await apiClient.post('/subscriptions/redeem', { code });
      alert(`兑换成功！获得 ${res.bt_granted} BT`);
    } catch (err) {
      if (err.response?.data?.error_code === 'ALREADY_USED') {
        alert('兑换码已被使用');
      } else if (err.response?.data?.error_code === 'EXPIRED') {
        alert('兑换码已过期');
      } else {
        alert('兑换码无效');
      }
    }
  };
  
  return (
    <div>
      <input 
        value={code} 
        onChange={e => setCode(e.target.value)}
        placeholder="输入兑换码"
      />
      <button onClick={handleRedeem}>兑换</button>
    </div>
  );
};
```

### 6.2 管理后台生成

```typescript
// 管理员批量生成兑换码
const generateCards = async () => {
  const res = await apiClient.post('/admin/redeem_cards/generate', {
    batch_size: 100,
    bt_value: 50,
    expires_at: '2026-12-31T23:59:59Z',
    prefix: 'PROMO-'
  });
  
  // 导出 CSV
  downloadCSV(res.cards, `redeem_cards_${res.batch_id}.csv`);
};
```

---

## 7. 相关文档

- **API 契约**: `homework_agent/API_CONTRACT.md` § C.6
- **产品需求**: `product_requirements.md` § 5.1.3
- **实现代码**: 
  - `homework_agent/api/subscriptions.py`
  - `homework_agent/api/admin.py`

---

**文档版本**: v1.0.0  
**最后更新**: 2026-01-30  
**状态**: 已实现并上线
