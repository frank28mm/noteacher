# Agent开发规则速查卡

> 快速参考，贴在显示器旁 📌

---

## 新功能开发Checklist

```python
# 1️⃣ 添加函数时
from homework_agent.utils.observability import trace_span, log_event, log_llm_usage

@trace_span("feature_name")  # ✅ 必须添加
async def new_feature(*, session_id: str, request_id: str):
    # 2️⃣ 记录开始
    log_event(logger, "feature_start",
              session_id=session_id,
              request_id=request_id,
              iteration=1)

    try:
        # 业务逻辑
        result = do_work()

        # 3️⃣ 记录LLM使用
        log_llm_usage(
            logger,
            request_id=request_id,
            session_id=session_id,
            model="your_model",
            provider="your_provider",
            usage=getattr(result, "usage", None),
            stage="feature_name",
        )

        # 4️⃣ 记录完成
        log_event(logger, "feature_done",
                  session_id=session_id,
                  request_id=request_id,
                  result_count=len(result))

        return result
    except Exception as e:
        # 5️⃣ 记录错误
        log_event(logger, "feature_error",
                  session_id=session_id,
                  request_id=request_id,
                  error=str(e),
                  error_type=e.__class__.__name__)
        raise
```

---

## PR提交前5分钟自检

```bash
# 0. 单元/契约测试（快）
python3 -m pytest -q

# 1. 运行replay测试
python3 -m pytest homework_agent/tests/test_replay.py -v

# 2. 收集metrics
# Offline metrics（不调用真实 provider；CI 默认用这个）
python3 scripts/collect_replay_metrics.py --output qa_metrics/metrics.json

# 可选：Live metrics（需要真实图片 + provider secrets）
# python3 homework_agent/scripts/collect_metrics.py \
#   --image-dir homework_agent/tests/replay_data/images \
#   --mode local \
#   --output qa_metrics/live_metrics.json

# 可选：Live metrics（不入库样本集：本机绝对路径 inventory）
# 1) 先维护 `homework_agent/tests/replay_data/samples_inventory.csv`
# 2) 本地运行（会真实调用 provider；需要 ARK_API_KEY/SILICON_API_KEY 等）
# python3 scripts/collect_inventory_live_metrics.py \
#   --inventory homework_agent/tests/replay_data/samples_inventory.csv \
#   --provider ark \
#   --output qa_metrics/inventory_live_metrics.json

# 3) 对比 live baseline（可选；首次可用 --update-baseline 初始化）
# python3 scripts/check_baseline.py \
#   --current qa_metrics/inventory_live_metrics_summary.json \
#   --baseline .github/baselines/live_metrics_baseline.json \
#   --threshold 0.05

# 3. 检查可观测性
python3 scripts/check_observability.py

# 4. 安全扫描
python3 -m bandit -r homework_agent -c bandit.yaml -x homework_agent/demo_ui.py -q
python3 -m pylint --disable=all --enable=E0602 homework_agent/

# 4.5 Baseline 更新（仅在合理变化时）
# 允许更新：新功能/bug修复提升/模型或Prompt升级带来预期变化
# 要求：PR 附 qa_metrics/report.html；PR 描述说明原因；按 PR 模板 baseline checklist
# 更新：
# cp qa_metrics/metrics_summary.json .github/baselines/metrics_baseline.json

# 5. 代码格式化
python3 -m black --check homework_agent/
python3 -m ruff check homework_agent/

# 6. E2E 冒烟（可选，本地优先；需要已启动后端 + provider secrets）
# python3 scripts/e2e_grade_chat.py --image-url https://example.com/image.jpg
# python3 scripts/e2e_grade_chat.py --image-file /abs/path/to/image.jpg
```

---

## 测试分层（规则2.4）

- Unit：不依赖网络/外部服务，必须快、可重复
- Contract：路由/schema/SSE 序列等最小不变量（TestClient + stub/mocks）
- Integration：Redis/队列/worker 等依赖（CI service 或本地 docker）
- E2E：`/uploads → /grade → /chat` 冒烟（本地优先，CI 可选）

---

## 常见错误 ❌ → 正确做法 ✅

| 错误做法 | 正确做法 |
|---------|---------|
| `print("Processing")` | `log_event(logger, "processing", ...)` |
| `logger.info("Tool called")` | `log_event(logger, "agent_tool_call", tool=name, ...)` |
| `async def func(): ...` | `@trace_span("func")\nasync def func(): ...` |
| `return {"error": str(e)}` | `return {"error_code": "PROCESS_FAILED", "message": "服务暂时不可用"}` |
| 直接改 prompt 且不留痕 | 更新 `homework_agent/prompts/*.yaml` 的 `version` 字段，并在 PR 说明变更原因 |
| `ALTER TABLE ADD COLUMN` | 写migration的up()和down() |

---

## log_event 必需字段

```python
# 最小集合（所有事件必须有）
log_event(logger, "event_name",
          session_id=str,    # 会话ID
          request_id=str,    # 请求ID
          iteration=int,     # 迭代次数（如适用）
          )

# 常用可选字段
{
    "user_id": str,         # 用户ID
    "tool": str,            # 工具名称
    "status": str,          # running/completed/error
    "duration_ms": int,     # 耗时
    "error": str,           # 错误信息
    "error_code": str,      # 错误代码
    "warning_code": str,    # 警告代码
}
```

---

## Prompt版本管理

```yaml
# homework_agent/prompts/feature.yaml
# 版本: v1.0.0
# 更新: 2025-01-15
# 原因: 新增功能X
# 作者: @yourname

system_prompt: |
  ...
```

```bash
# 更新Prompt时
# 1) 编辑 `homework_agent/prompts/<name>.yaml`，提升 `version` 字段
# 2) 在 PR 描述里写清：变更原因 + 预期影响 + 回归样本
git commit -m "chore(prompts): bump <name> version - <reason>"
```

---

## 错误代码标准

```python
# homework_agent/utils/error_codes.py

# 工具错误
TOOL_ERROR = "tool_error"
TOOL_TIMEOUT = "tool_timeout"
TOOL_DEGRADED = "tool_degraded"  # 降级但可用

# 解析错误
PARSE_FAILED = "parse_failed"
TOOL_PARSE_FAILED = "tool_parse_failed"

# Agent退出
MAX_ITERATIONS_REACHED = "max_iterations_reached"
CONFIDENCE_NOT_MET = "confidence_not_met"

# 安全
PII_DETECTED = "pii_detected"
PROMPT_INJECTION = "prompt_injection"
NEEDS_REVIEW = "needs_review"

# 使用
log_event(logger, "tool_error",
          error_code=TOOL_DEGRADED,
          tool="diagram_slice",
          reason="roi_not_found")
```

---

## 回滚命令

```bash
# 当前项目未统一部署形态（K8s/Docker/Serverless）。
# 建议的最小回滚策略：
# 1) git revert 引入问题的提交
# 2) 走同一条 CI/CD 流水线重新部署
# 3) 如已支持 feature flag，则关闭对应开关作为临时止血
```

---

## 敏感信息脱敏

```python
# URL
from homework_agent.utils.observability import redact_url
safe_url = redact_url(url_with_token)

# 数据
from homework_agent.utils.observability import _safe_value
safe_data = _safe_value(user_data)

# 日志
log_event(logger, "api_call",
          url=redact_url(url),           # ✅
          user_id=user_id,                # ✅
          # 不要: password=xxx, token=xxx  # ❌
          )
```

---

## 常用命令

```bash
# 查看replay测试状态
python3 -m pytest homework_agent/tests/test_replay.py -v

# 生成metrics报告（Offline / CI-safe）
python3 scripts/collect_replay_metrics.py --output qa_metrics/metrics.json

# 可选：Live metrics（需要真实图片 + provider secrets）
# python3 homework_agent/scripts/collect_metrics.py \
#   --image-dir homework_agent/tests/replay_data/images \
#   --mode local \
#   --output qa_metrics/live_metrics.json

# （可选）生成 HTML 报告
python3 scripts/generate_metrics_report.py --input qa_metrics/metrics_summary.json --output qa_metrics/report.html

# （可选）从日志回收 needs_review 案例 → replay 候选（用于补充 Golden Set）
python3 scripts/extract_replay_candidates.py --log logs/your_run.jsonl --out qa_replay_candidates/

# （P2）Reviewer 队列（仅内部/运维使用）
# 开启：
#   export REVIEW_API_ENABLED=1
#   export REVIEW_ADMIN_TOKEN=your_token
# 查询（需要 header）：
#   curl -H "X-Admin-Token: your_token" http://localhost:8000/api/v1/review/items

# 查看当前Git状态
git status
git log -1 --oneline

# 检查代码质量
black --check homework_agent/
ruff check homework_agent/
```

---

## CI失败处理

```bash
# 1. 查看失败日志
# 在GitHub Actions页面查看详细输出

# 2. 本地复现
python3 -m pytest homework_agent/tests/test_replay.py -v

# 3. 检查metrics
cat qa_metrics/metrics_summary.json

# 4. 修复后验证
# 提交新commit，CI自动重新运行
```

---

## 紧急回滚流程

```bash
# 1. 立即止血：关闭入口/降低流量/启用更保守策略（如 needs_review）
# 2. 回滚代码/Prompt：git revert 引入问题的提交
# 3. 重新部署：走同一条 CI/CD 流水线（由项目部署脚本决定）
# 4. 复盘与固化：把失败 case 写入 replay_data，并更新 baseline
```

---

**打印此页，贴在显示器旁！** 🖨️

**文档版本**: v1.0 | **更新日期**: 2025年12月
