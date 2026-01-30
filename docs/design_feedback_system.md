# 反馈系统设计 (Feedback System Design)

> **文档类型**: 系统设计文档  
> **功能**: 用户反馈提交、管理员回复、未读检查  
> **状态**: ✅ 已实现

---

## 1. 概述

反馈系统支持用户提交产品使用反馈，管理员查看并回复，形成闭环的用户支持流程。

**核心场景**:
- 用户报告批改错误
- 用户建议新功能
- 用户投诉问题
- 客服主动回复解答

---

## 2. 数据模型

### 2.1 数据库表结构

#### feedback_messages (反馈消息表)

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `user_id` | UUID | 用户 ID（外键） |
| `sender` | VARCHAR | 发送者：user / admin |
| `content` | TEXT | 消息内容 |
| `images` | JSON | 图片 URL 列表（可选） |
| `is_read` | BOOLEAN | 是否已读 |
| `created_at` | TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | 更新时间 |

### 2.2 消息流向

```
用户发送反馈 → 管理员查看 → 管理员回复 → 用户收到通知
     ↑                                              ↓
     └──────────── 用户可继续追问 ←────────────────┘
```

---

## 3. 业务流程

### 3.1 用户提交反馈

**触发**: 用户在"我的-帮助与反馈"页面

**API**: `POST /feedback`

**流程**:
1. 用户填写反馈表单：
   - 反馈内容（必填）
   - 上传图片（可选，截图或照片 URL 列表）
2. 后端创建 feedback 记录：
   - `sender = "user"`
   - `is_read = false`
   - `images = []`（图片 URL 列表）
3. 返回提交成功

**注意**: 当前版本不支持直接关联 submission 或题目，如需关联请在文本中描述。

**请求示例**:
```json
{
  "content": "第3题批改有误，正确答案应该是...",
  "images": ["https://example.com/screenshot1.jpg"]
}
```

### 3.2 管理员查看反馈

**触发**: 管理员登录后台

**API**: 
- `GET /admin/feedback/users` - 查看有反馈的用户列表
- `GET /admin/feedback/{user_id}` - 查看具体用户的反馈历史

**流程**:
1. 管理员查看"有反馈的用户"列表
2. 点击用户查看对话历史
3. 系统按时间倒序展示所有消息
4. 未读消息高亮显示

### 3.3 管理员回复

**API**: `POST /admin/feedback/{user_id}`

**流程**:
1. 管理员输入回复内容
2. 后端创建反馈记录：
   - `is_from_user = false`
   - `parent_id` = 指向用户原消息
   - `is_read = false`（对用户而言是未读）
3. （可选）触发推送通知用户
4. 返回回复成功

**请求示例**:
```json
{
  "content": "感谢您的反馈，已核实并修正。",
  "parent_id": "msg_xxx"  // 回复哪条消息
}
```

### 3.4 用户查看反馈历史

**API**: `GET /feedback`

**流程**:
1. 用户进入"帮助与反馈"页面
2. 展示所有历史反馈（按时间倒序）
3. 管理员回复的消息标记为"官方回复"
4. 用户可继续追问（创建新的 feedback 记录，parent_id 指向之前消息）

**响应示例**:
```json
{
  "messages": [
    {
      "message_id": "msg_002",
      "content": "已核实并修正，感谢您的反馈！",
      "is_from_user": false,
      "is_read": true,
      "created_at": "2026-01-20T10:05:00Z",
      "admin_name": "客服小王"
    },
    {
      "message_id": "msg_001",
      "content": "第3题批改有误...",
      "is_from_user": true,
      "is_read": true,
      "submission_id": "sub_xxx",
      "created_at": "2026-01-20T10:00:00Z"
    }
  ],
  "total": 2
}
```

### 3.5 未读检查

**API**: `GET /feedback/check_unread`

**使用场景**: 
- App 启动时检查是否有新回复
- 消息红点提示

**响应**:
```json
{
  "has_unread": true,
  "unread_count": 2
}
```

---

## 4. 功能特性

### 4.1 关联上下文

用户反馈时可关联：
- **具体提交**: 方便管理员查看原始图片和批改结果
- **具体题目**: 精确定位到某道错题

**实现**:
```json
{
  "content": "这道题批改错了",
  "submission_id": "sub_xxx",  // 关联提交
  "item_id": "item_yyy"        // 关联题目（对应 wrong_items 中的 item_id）
}
```

管理员查看时可一键跳转：
- 查看原始 submission
- 查看题目详情
- 直接进入题目复核界面

### 4.2 对话线程

支持多轮对话：

```
用户: "第3题错了"
  ↓
客服: "已核实，确实误判"
  ↓
用户: "那第5题呢？" (parent_id → 客服回复)
  ↓
客服: "第5题是正确的"
```

通过 `parent_id` 构建对话树。

### 4.3 状态管理

**对用户**:
- `is_read`: 用户是否已读管理员回复
- 前端标记已读：再次打开对话时自动标记

**对管理员**:
- 新反馈默认"未处理"
- 管理员回复后标记为"已回复"
- 支持手动标记"已解决"

---

## 5. 管理后台功能

### 5.1 用户列表

**API**: `GET /admin/feedback/users`

展示有反馈的用户：
- 用户名/手机号
- 最近反馈时间
- 未读消息数
- 反馈总数

### 5.2 快捷操作

- **一键查看提交**: 从反馈直接跳转到关联 submission
- **快速修正**: 对于批改错误，可直接进入审核队列修正
- **批量回复**: 同类问题批量回复（模板消息）

---

## 6. 通知机制

### 6.1 用户侧通知

当管理员回复时，通知用户：

**渠道**:
- App 内红点（通过 `check_unread` API）
- （可选）推送通知（Push）
- （可选）短信通知（重要问题）

**触发时机**:
- 管理员回复后立即通知
- 用户首次打开反馈页面时拉取

### 6.2 管理员侧通知

新反馈通知管理员：

**渠道**:
- 管理后台未读数字
- （可选）企业微信/钉钉群机器人
- （可选）邮件通知

---

## 7. 统计与分析

### 7.1 反馈统计

**维度**:
- 日/周/月反馈量
- 反馈类型分布（纠错/建议/投诉/其他）
- 响应时长（用户提交到管理员首次回复）
- 解决率

### 7.2 热点问题

通过 NLP 分析反馈内容：
- 高频关键词
- 情感分析（正面/负面）
- 聚类分析（同类问题归类）

---

## 8. 安全与隐私

### 8.1 数据权限

- 用户只能查看自己的反馈
- 管理员可查看所有用户反馈
- 敏感信息（手机号）脱敏展示

### 8.2 内容审核

- 用户提交内容 XSS 过滤
- 敏感词过滤
- 图片上传限制（如允许截图）

### 8.3 审计日志

- 记录管理员查看/回复行为
- 记录用户提交行为
- 支持导出用于客服质检

---

## 9. 集成示例

### 9.1 前端反馈表单

```typescript
const FeedbackForm = () => {
  const [content, setContent] = useState('');
  const [recentSubmissions, setRecentSubmissions] = useState([]);
  
  // 加载最近提交用于关联
  useEffect(() => {
    apiClient.get('/submissions?limit=5').then(res => {
      setRecentSubmissions(res.data.items);
    });
  }, []);
  
  const handleSubmit = async () => {
    await apiClient.post('/feedback', {
      content,
      submission_id: selectedSubmission?.id,
      item_id: selectedItem?.id
    });
    alert('反馈提交成功，我们会尽快处理');
  };
  
  return (
    <div>
      <textarea 
        value={content}
        onChange={e => setContent(e.target.value)}
        placeholder="请描述您遇到的问题..."
      />
      <select onChange={e => setSelectedSubmission(e.target.value)}>
        <option>关联最近提交（可选）</option>
        {recentSubmissions.map(sub => (
          <option key={sub.id} value={sub.id}>
            {sub.subject} - {sub.created_at}
          </option>
        ))}
      </select>
      <button onClick={handleSubmit}>提交反馈</button>
    </div>
  );
};
```

### 9.2 管理后台对话界面

```typescript
const AdminFeedbackChat = ({ userId }) => {
  const [messages, setMessages] = useState([]);
  const [reply, setReply] = useState('');
  
  // 拉取对话历史
  useEffect(() => {
    apiClient.get(`/admin/feedback/${userId}`).then(res => {
      setMessages(res.data.messages);
    });
  }, [userId]);
  
  const handleReply = async () => {
    await apiClient.post(`/admin/feedback/${userId}`, {
      content: reply,
      parent_id: messages[0]?.message_id  // 回复最新消息
    });
    setReply('');
    // 刷新列表
  };
  
  return (
    <div className="chat-container">
      {messages.map(msg => (
        <div key={msg.message_id} className={msg.is_from_user ? 'user' : 'admin'}>
          <div className="content">{msg.content}</div>
          <div className="time">{msg.created_at}</div>
          {msg.submission_id && (
            <button onClick={() => viewSubmission(msg.submission_id)}>
              查看关联提交
            </button>
          )}
        </div>
      ))}
      <div className="reply-box">
        <textarea value={reply} onChange={e => setReply(e.target.value)} />
        <button onClick={handleReply}>回复</button>
      </div>
    </div>
  );
};
```

---

## 10. 相关文档

- **API 契约**: `homework_agent/API_CONTRACT.md` § C.7
- **产品需求**: `product_requirements.md` § 5.2
- **实现代码**: `homework_agent/api/feedback.py`

---

**文档版本**: v1.0.0  
**最后更新**: 2026-01-30  
**状态**: 已实现并上线
