# 前端代码自检与反馈报告

## 1. 概览 (Executive Summary)

经过对 codebase 的深度自检，我已核实了两位同事的反馈。整体而言，反馈 **高度准确**，尤其是在**代码稳定性/内存泄漏**（同事A）和**完成度/设计还原**（同事B）方面。

项目目前处于 **Visual Prototype (高保真原型)** 阶段，而非 Production Ready (生产就绪) 阶段。虽然 UI 框架和核心流程已跑通，但缺乏健壮性工程实践（清理、错误边界、Env配置）和真实数据接入。

## 2. 问题核实详情

### 🔴 严重问题 (Critical) - 已核实

| 问题描述 | 核实结果 | 详情 |
| :--- | :--- | :--- |
| **内存泄漏 (useJobPolling)** | ✅ 确认 | `setTimeout` 确实没有在组件卸载时严谨清理，网络错误时会无限重试。 |
| **内存泄漏 (Toast)** | ✅ 确认 | `showToast` 中的 `setTimeout` 在快速卸载时会报错，未追踪 timer ID。 |
| **竞态条件 (Upload)** | ✅ 确认 | 使用了简单的 `isMounted` 变量闭包，非最佳实践，易出错。 |
| **Camera 仅为占位** | ✅ 确认 | 仅使用了 `<input type="file" capture>`，虽然符合 H5 最简实现，但确实缺少取景流体验。 |
| **页面完成度 (Stub)** | ⚠️ 部分确认 | `Home.tsx` 确实为空。但 `ReportDetail`, `DataArchive` 等页面 **已存在**，只是使用 Mock 数据，同事 B 称其 "Missing" 可能指缺乏真实对接。 |

### 🟠 中等问题 (Major) - 已核实

| 问题描述 | 核实结果 | 详情 |
| :--- | :--- | :--- |
| **Hardcoded API URL** | ✅ 确认 | `src/services/api.ts` 硬编码了 `/api/v1`，未对接 Vite 环境变量。 |
| **Hardcoded TotalPages** | ✅ 确认 | `Result.tsx` 硬编码了 `totalPages: 10`，影响超时逻辑准确性。 |
| **any 类型泛滥** | ✅ 确认 | API 响应确实大量使用了 `any`，缺少 `types/api.ts` 定义。 |
| **navigate(-1)** | ✅ 确认 | `AITutor` 使用了 `navigate(-1)`，存在跳出应用的风险。 |

### 🟡 轻微/优化问题 (Minor) - 已核实

| 问题描述 | 核实结果 | 详情 |
| :--- | :--- | :--- |
| **CSS 字符串拼接** | ✅ 确认 | `Camera.tsx` 等部分组件未完全使用 `cn()`，存在长字符串。 |
| **缺少 ErrorBoundary** | ✅ 确认 | `App.tsx` 未包裹错误边界，报错即白屏。 |
| **缺少 SEO/I18n** | ✅ 确认 | 目前纯 CSR 且中文硬编码，符合当前原型阶段特征，但需规划。 |

---

## 3. 修复与行动计划 (Remediation Plan)

我建议按以下优先级进行修复：

### Phase 6: Stability & Engineering (优先级 P0 - 立即执行)
目标：修复内存泄漏，确保应用不崩溃。
1.  **Refactor Hooks**: 重构 `useJobPolling` 和 `Toast`，使用 `useRef` 严谨管理 Timers。
2.  **Env Configuration**: 创建 `.env` 和 `vite-env.d.ts`，配置动态 Base URL。
3.  **Global Error Boundary**: 引入 `react-error-boundary` 防止白屏。
4.  **Fix Race Conditions**: 在 `Upload` 等异步流中引入 `AbortController` 或严谨的 Mounted Ref。

### Phase 7: Data Integration (优先级 P1 - 关键路经)
目标：对接真实数据，移除 Mock。
1.  **API Types**: 定义完整 TypeScript 接口 (`types/job.ts`, `types/report.ts`)。
2.  **Connect Pages**: 将 `Upload` -> `Result` -> `ReportDetail` 流程彻底打通真实数据。
3.  **Dynamic Polling**: 基于真实 `totalPages` 计算超时。

### Phase 8: UX Polish (优先级 P2 - 体验提升)
1.  **Real Camera**: 尝试集成 `react-webcam` 或原生 `getUserMedia` (若环境允许)。
2.  **Performance**: 引入 `React.memo` 和 `Suspense` 路由懒加载。
3.  **Design Tokens**: 统一 tailwind config 中的阴影变量。

## 4. 结论
两位同事的反馈非常中肯。我们目前拥有一个 "好看的躯壳" (Beautiful Shell)，现在的任务是赋予它 "强壮的筋骨" (Robust Engineering)。

**建议立即启动 Phase 6 修复 P0 级内存泄漏与配置问题。**
