# 前端架构设计 (Frontend Architecture)

> **文档类型**: 架构设计文档  
> **技术栈**: React + TypeScript + Vite  
> **位置**: `homework_frontend/`  
> **状态**: ✅ 已实现

---

## 1. 概述

作业检查大师的前端应用，提供完整的用户界面：作业上传、批改结果展示、AI 辅导对话、错题本、学情报告、个人中心等。

**架构特点**:
- **现代技术栈**: React 19 + TypeScript + Vite
- **响应式设计**: 适配桌面端和移动端
- **数据驱动**: SWR 处理数据获取和缓存
- **流式交互**: 原生 SSE 处理 AI 辅导对话
- **类型安全**: 完整的 TypeScript 类型定义

---

## 2. 技术栈

### 2.1 核心框架

| 技术 | 版本 | 用途 |
|------|------|------|
| **React** | 19.2.0 | UI 框架 |
| **TypeScript** | 5.9.3 | 类型系统 |
| **Vite** | 7.2.4 | 构建工具 |
| **React Router** | 7.12.0 | 路由管理 |

### 2.2 UI 与样式

| 技术 | 版本 | 用途 |
|------|------|------|
| **Tailwind CSS** | 3.4.17 | 原子化 CSS |
| **Framer Motion** | 12.26.1 | 动画效果 |
| **clsx + tailwind-merge** | latest | 类名处理 |

### 2.3 数据与状态

| 技术 | 版本 | 用途 |
|------|------|------|
| **axios** | 1.13.2 | HTTP 客户端 |
| **SWR** | 2.3.8 | 数据获取与缓存 |

### 2.4 特殊功能

| 技术 | 版本 | 用途 |
|------|------|------|
| **KaTeX** | 0.16.27 | 数学公式渲染 |
| **react-easy-crop** | 5.5.6 | 图片裁剪 |

### 2.5 测试

| 技术 | 版本 | 用途 |
|------|------|------|
| **Vitest** | 4.0.17 | 单元测试 |
| **Testing Library** | latest | React 组件测试 |

---

## 3. 项目结构

```
homework_frontend/
├── public/                    # 静态资源
│   └── vite.svg
├── src/
│   ├── App.tsx               # 根组件
│   ├── AppRouter.tsx         # 路由配置
│   ├── main.tsx              # 入口文件
│   ├── vite-env.d.ts         # Vite 类型声明
│   │
│   ├── api/                  # API 类型定义
│   │   └── types.ts
│   │
│   ├── components/           # 通用组件
│   │   ├── ui/              # 基础 UI 组件
│   │   │   ├── Button.tsx
│   │   │   ├── Card.tsx
│   │   │   ├── Header.tsx
│   │   │   ├── BackButton.tsx
│   │   │   ├── Toast.tsx
│   │   │   ├── Skeleton.tsx
│   │   │   └── ...
│   │   ├── ImageCropper.tsx # 图片裁剪组件
│   │   ├── MathText.tsx     # 数学文本渲染
│   │   └── QuestionText.tsx # 题目文本渲染
│   │
│   ├── contexts/            # React Context
│   │   ├── AuthContext.tsx  # 认证上下文
│   │   └── ProfileContext.tsx # 当前子女档案上下文
│   │
│   ├── hooks/               # 自定义 Hooks
│   │   ├── useAppSWR.ts     # SWR 封装
│   │   ├── useJobPolling.ts # 任务轮询
│   │   └── ...
│   │
│   ├── pages/               # 页面组件
│   │   ├── Home.tsx         # 首页/仪表盘
│   │   ├── Upload.tsx       # 上传作业
│   │   ├── Camera.tsx       # 拍照上传
│   │   ├── Result.tsx       # 批改结果
│   │   ├── ResultSummary.tsx # 结果摘要
│   │   ├── QuestionDetail.tsx # 题目详情
│   │   ├── AITutor.tsx      # AI 辅导
│   │   ├── Analysis.tsx     # 学情分析
│   │   ├── ReportDetail.tsx # 报告详情
│   │   ├── ReportHistory.tsx # 历史报告
│   │   ├── ReportGenerating.tsx # 报告生成中
│   │   ├── ReviewFlow.tsx   # 错题复习
│   │   ├── History.tsx      # 提交历史
│   │   ├── DataArchive.tsx  # 数据归档
│   │   ├── Mine.tsx         # 个人中心
│   │   ├── MinePersonalInfo.tsx # 个人信息
│   │   ├── MineRedemptions.tsx  # 兑换记录
│   │   ├── MineHelpFeedback.tsx # 帮助反馈
│   │   ├── ProfileManagement.tsx # 子女档案管理
│   │   ├── Login.tsx        # 登录
│   │   ├── Subscribe.tsx    # 订阅
│   │   ├── Admin.tsx        # 管理员后台
│   │   └── ...
│   │
│   ├── services/            # 服务层
│   │   ├── api.ts           # axios 实例与拦截器
│   │   ├── auth.ts          # 认证服务
│   │   └── subscription.ts  # 订阅服务
│   │
│   ├── styles/              # 样式文件
│   │   └── globals.css
│   │
│   └── utils/               # 工具函数
│       └── helpers.ts
│
├── index.html              # HTML 模板
├── package.json            # 依赖配置
├── tsconfig.json           # TypeScript 配置
├── tsconfig.app.json       # App TS 配置
├── tsconfig.node.json      # Node TS 配置
├── vite.config.ts          # Vite 配置
├── tailwind.config.js      # Tailwind 配置
├── postcss.config.js       # PostCSS 配置
└── eslint.config.js        # ESLint 配置
```

---

## 4. 核心模块详解

### 4.1 API 集成 (services/api.ts)

```typescript
// axios 实例配置
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json'
  }
});

// 请求拦截器：添加认证 token
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  // 添加当前 profile_id
  const profileId = localStorage.getItem('active_profile_id');
  if (profileId) {
    config.headers['X-Profile-Id'] = profileId;
  }
  return config;
});

// 响应拦截器：错误处理
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token 过期，跳转登录
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);
```

### 4.2 数据获取 (hooks/useAppSWR.ts)

```typescript
import useSWR from 'swr';
import { apiClient } from '@/services/api';

// SWR 全局配置
export const useAppSWR = <T>(url: string | null) => {
  return useSWR<T>(
    url,
    async (url) => {
      const res = await apiClient.get(url);
      return res.data;
    },
    {
      refreshInterval: 0,       // 默认不自动刷新
      revalidateOnFocus: true,  // 窗口聚焦时重新验证
      dedupingInterval: 2000,   // 2秒内重复请求去重
    }
  );
};
```

**使用示例**:
```typescript
const { data: submissions, error, isLoading } = useAppSWR('/submissions');
```

### 4.3 任务轮询 (hooks/useJobPolling.ts)

```typescript
// 异步任务状态轮询
export const useJobPolling = (jobId: string | null) => {
  const { data, error } = useSWR(
    jobId ? `/jobs/${jobId}` : null,
    async (url) => {
      const res = await apiClient.get(url);
      return res.data;
    },
    {
      refreshInterval: (data) => {
        // 任务未完成时每 2 秒轮询
        if (data?.status === 'processing' || data?.status === 'queued') {
          return 2000;
        }
        return 0; // 完成后停止轮询
      },
    }
  );
  
  return { job: data, error, isComplete: data?.status === 'done' };
};
```

### 4.4 SSE 流式处理 (pages/AITutor.tsx)

```typescript
// AI 辅导 SSE 连接
const startChat = async (question: string) => {
  const res = await fetch(`${apiClient.defaults.baseURL}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({
      question,
      session_id: currentSessionId,
      history: chatHistory,
    }),
  });
  
  // 读取 ReadableStream
  const reader = res.body?.getReader();
  const decoder = new TextDecoder();
  
  while (reader) {
    const { done, value } = await reader.read();
    if (done) break;
    
    // 解析 SSE 格式
    const chunk = decoder.decode(value);
    const lines = chunk.split('\n\n');
    
    for (const line of lines) {
      if (line.startsWith('data:')) {
        const data = JSON.parse(line.slice(5));
        // 更新聊天内容
        appendMessage(data);
      }
    }
  }
};
```

### 4.5 路由配置 (AppRouter.tsx)

```typescript
import { BrowserRouter, Routes, Route } from 'react-router-dom';

export const AppRouter = () => (
  <BrowserRouter>
    <Routes>
      {/* 公开路由 */}
      <Route path="/login" element={<Login />} />
      
      {/* 需要认证的路由 */}
      <Route element={<AuthGuard />}>
        <Route path="/" element={<Home />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="/result/:jobId" element={<Result />} />
        <Route path="/tutor/:sessionId" element={<AITutor />} />
        <Route path="/mistakes" element={<ReviewFlow />} />
        <Route path="/reports" element={<ReportHistory />} />
        <Route path="/history" element={<History />} />
        <Route path="/mine" element={<Mine />} />
        <Route path="/profiles" element={<ProfileManagement />} />
      </Route>
      
      {/* 管理员路由 */}
      <Route element={<AdminGuard />}>
        <Route path="/admin" element={<Admin />} />
      </Route>
    </Routes>
  </BrowserRouter>
);
```

### 4.6 状态管理

#### 认证状态 (contexts/AuthContext.tsx)

```typescript
interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  login: (phone: string, code: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  
  const login = async (phone: string, code: string) => {
    const res = await apiClient.post('/auth/sms/verify', { phone, code });
    localStorage.setItem('access_token', res.data.access_token);
    setUser(res.data.user);
  };
  
  const logout = () => {
    localStorage.removeItem('access_token');
    setUser(null);
  };
  
  return (
    <AuthContext.Provider value={{ user, isAuthenticated: !!user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};
```

#### 当前档案状态 (contexts/ProfileContext.tsx)

```typescript
// 管理当前选中的子女档案
interface ProfileContextType {
  activeProfile: Profile | null;
  profiles: Profile[];
  setActiveProfile: (id: string) => void;
}
```

---

## 5. 后端 API 对接

### 5.1 调用的后端端点

| 功能 | 端点 | 前端页面 |
|------|------|---------|
| 认证 | `POST /auth/sms/*`, `POST /auth/login/email` | Login.tsx |
| 用户配额 | `GET /me/quota` | Mine.tsx |
| 子女档案 | `GET/POST/PATCH/DELETE /me/profiles` | ProfileManagement.tsx |
| 上传作业 | `POST /uploads`, `POST /grade` | Upload.tsx |
| 查询任务 | `GET /jobs/{id}` | useJobPolling.ts |
| 获取提交 | `GET /submissions/{id}` | Result.tsx |
| AI 辅导 | `POST /chat` (SSE) | AITutor.tsx |
| 错题本 | `GET/POST /mistakes/*` | ReviewFlow.tsx |
| 学情报告 | `GET/POST /reports/*` | ReportHistory.tsx |
| 兑换码 | `POST /subscriptions/redeem` | MineRedemptions.tsx |
| 反馈 | `GET/POST /feedback` | MineHelpFeedback.tsx |

### 5.2 环境变量

```bash
# .env.local
VITE_API_BASE_URL=http://localhost:8000/api/v1  # 后端 API 地址
```

---

## 6. 构建与部署

### 6.1 开发命令

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build

# 运行测试
npm run test

# 代码检查
npm run lint
```

### 6.2 生产构建

```bash
npm run build
# 输出到 dist/ 目录
```

### 6.3 部署

- **静态托管**: 阿里云 OSS + CDN
- **Docker**: 可打包为 nginx 容器
- **集成部署**: 与后端一起部署到 ACK

---

## 7. 性能优化

### 7.1 代码分割

```typescript
// 路由懒加载
const AITutor = lazy(() => import('./pages/AITutor'));
```

### 7.2 图片优化

- 上传前压缩
- 使用 WebP 格式
- 懒加载非首屏图片

### 7.3 缓存策略

- SWR 自动缓存 GET 请求
- localStorage 缓存用户配置
- 图片 CDN 缓存

---

## 8. 测试策略

### 8.1 单元测试

```typescript
// __tests__/components/Button.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { Button } from '@/components/ui/Button';

test('Button renders and handles click', () => {
  const handleClick = vi.fn();
  render(<Button onClick={handleClick}>Click me</Button>);
  
  fireEvent.click(screen.getByText('Click me'));
  expect(handleClick).toHaveBeenCalled();
});
```

### 8.2 E2E 测试

使用 Playwright 或 Cypress 测试关键流程：
- 登录 → 上传 → 批改 → 查看结果
- AI 辅导对话
- 错题复习流程

---

## 9. 相关文档

- **后端 API**: `homework_agent/API_CONTRACT.md`
- **系统架构**: `system_architecture.md` § 2.1
- **产品需求**: `product_requirements.md`

---

**文档版本**: v1.0.0  
**最后更新**: 2026-01-30  
**状态**: 已实现并上线
