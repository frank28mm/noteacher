# Agent 开发规则手册

> **核心理念**: 将生产就绪要求融入开发日常，而非最后补齐

**适用人员**: 所有参与Agent开发的工程师、AI工程师、Prompt工程师

**更新日期**: 2025年12月

---

## 规则总览

| 规则类别 | 优先级 | 检查方式 |
|---------|--------|----------|
| **可观测性优先** | P0 | Code Review |
| **评估驱动开发** | P0 | CI门禁 |
| **安全左移** | P0 | Security Scan |
| **版本可追溯** | P1 | Git Hooks |
| **变更可回滚** | P1 | Deployment Check |

---

## 一、可观测性优先 (Observability-First)

### 规则1.1: 所有新函数必须添加Tracing

**要求**: 每个新增的业务函数必须使用 `@trace_span` 装饰器

```python
# ✅ 正确示例
from homework_agent.utils.observability import trace_span

@trace_span("grade_homework")
async def grade_homework(*, images: List[ImageRef], subject: Subject):
    # 函数实现
    pass

# ❌ 错误示例
async def grade_homework(*, images: List[ImageRef], subject: Subject):
    # 缺少trace_span
    pass
```

**检查清单**:
- [ ] 函数有 `@trace_span` 装饰器
- [ ] Span名称清晰描述操作类型（如 `agent_tool_call`, `ocr_process`）
- [ ] 异常情况会被自动捕获（`@trace_span` 内置）

**Code Review要点**:
```markdown
## 可观测性检查
- [ ] 新函数有 @trace_span
- [ ] Span名称符合命名规范
```

---

### 规则1.2: 关键事件必须记录结构化日志

**要求**: 所有关键业务事件必须使用 `log_event()` 记录

```python
# ✅ 正确示例
from homework_agent.utils.observability import log_event

log_event(logger, "agent_tool_call",
          session_id=session_id,
          request_id=request_id,      # 必须包含
          tool=tool_name,
          status="running",
          iteration=iteration,        # 必须包含
          user_id=user_id)            # 为多租户预留

# ❌ 错误示例
print(f"Tool {tool_name} called")  # 不可搜索，无结构
logger.info(f"Tool {tool_name} called")  # 缺少关键字段
```

**必须包含的字段**:
```python
# 所有log_event必须包含
{
    "session_id": str,      # 会话ID
    "request_id": str,      # 请求ID（同一请求的上下文）
    "iteration": int,       # 当前迭代次数（如果是Loop）
}

# 根据场景选择性包含
{
    "user_id": str,         # 用户ID（多租户场景）
    "tool": str,            # 工具名称（工具调用时）
    "status": str,          # 状态（running/completed/error）
    "duration_ms": int,     # 耗时（完成时）
    "error": str,           # 错误信息（失败时）
}
```

**检查清单**:
- [ ] 使用 `log_event()` 而非 `print()` 或 `logger.info()`
- [ ] 包含 `session_id`, `request_id`, `iteration`
- [ ] 事件名称清晰（如 `agent_tool_call`，而非 `log1`）
- [ ] 敏感信息已脱敏

---

### 规则1.3: LLM调用必须记录Token使用

**要求**: 每次LLM调用后必须记录Token消耗

```python
# ✅ 正确示例
from homework_agent.utils.observability import log_llm_usage

text = await llm.generate(...)
log_llm_usage(logger,
               request_id=request_id,
               session_id=session_id,
               model="doubao-pro-32k",
               provider="ark",
               usage=text.usage if hasattr(text, 'usage') else {},
               stage="planner")  # planner/reflector/aggregator

# ❌ 错误示例
text = await llm.generate(...)
# 未记录usage，无法追踪成本
```

**检查清单**:
- [ ] 每次LLM调用后记录usage
- [ ] 包含model, provider, stage信息
- [ ] 兼容usage为空的情况

---

## 二、评估驱动开发 (Evaluation-Driven Development)

### 规则2.1: 新功能前先写评估用例

**要求**: 新功能必须在提交PR前添加评估用例到Replay Dataset

```bash
# 1. 添加测试样本
homework_agent/tests/replay_data/images/new_feature_001.jpg
homework_agent/tests/replay_data/samples/new_feature_001.json

# 2. 编写测试用例
# homework_agent/tests/test_replay.py
@pytest.mark.replay
def test_new_feature_xyz():
    """测试新功能XYZ"""
    # 测试代码
```

**评估用例覆盖标准**:
```markdown
## 最小覆盖（P0）
- [ ] 正常场景：1-2个样本
- [ ] 边界场景：1个样本（如空输入、极端值）

## 完整覆盖（P1）
- [ ] 正常场景：3-5个样本
- [ ] 边界场景：2-3个样本
- [ ] 错误场景：1-2个样本
```

**检查清单**:
- [ ] 新功能有对应的replay测试用例
- [ ] 测试用例包含正常和边界情况
- [ ] 测试可在本地通过

---

### 规则2.2: PR必须通过Replay回归评测

**要求**: 所有PR必须通过CI中的Replay评估门禁

```yaml
# 示例：建议新增 `.github/workflows/quality_gate.yml`（当前仓库默认使用 `.github/workflows/ci.yml`）
- name: Replay Evaluation
  run: |
    python3 -m pytest homework_agent/tests/test_replay.py -v
    # Offline metrics (no provider calls; safe for CI by default)
    python3 scripts/collect_replay_metrics.py --output qa_metrics/metrics.json

    # Optional: Live metrics (requires real images + provider secrets)
    # python3 homework_agent/scripts/collect_metrics.py \
    #   --image-dir homework_agent/tests/replay_data/images \
    #   --mode local \
    #   --output qa_metrics/live_metrics.json
```

**失败阻断条件（示例）**:
```bash
python3 scripts/check_baseline.py \
  --current qa_metrics/metrics_summary.json \
  --baseline .github/baselines/metrics_baseline.json \
  --threshold 0.05
```

**Baseline 初始化**:
- baseline 文件位置：`.github/baselines/metrics_baseline.json`
- 更新 baseline（需要在 PR 里说明原因，并附 replay/metrics 产物）：
  - `python3 scripts/check_baseline.py --current qa_metrics/metrics_summary.json --baseline .github/baselines/metrics_baseline.json --update-baseline`

**检查清单**:
- [ ] PR触发CI后自动运行replay测试
- [ ] Metrics报告生成在 `qa_metrics/metrics.json`
- [ ] 回归检测失败时自动阻断PR

---

### 规则2.3: 评估数据必须可追溯

**要求**: 每次评估运行必须有唯一标识和完整记录

```python
# ✅ 正确示例
def run_evaluation(dataset_name: str):
    """运行评估"""
    eval_id = f"eval_{dataset_name}_{int(time.time())}"
    log_event(logger, "evaluation_start",
              eval_id=eval_id,
              dataset=dataset_name,
              git_commit=get_git_commit(),
              git_branch=get_git_branch())

    results = run_tests()

    # 保存完整结果
    save_evaluation_results(eval_id, {
        "dataset": dataset_name,
        "git_commit": get_git_commit(),
        "timestamp": time.time(),
        "results": results,
    })

# ❌ 错误示例
results = run_tests()
# 无法追溯这次运行的代码版本
```

**检查清单**:
- [ ] 每次评估有唯一eval_id
- [ ] 记录git commit和branch
- [ ] 结果持久化到文件或数据库

**实现约定（当前仓库）**：
- Offline replay（CI-safe）：`python3 scripts/collect_replay_metrics.py` 会在 `qa_metrics/metrics_summary.json` 中写入 `eval_id/generated_at/git_commit/git_branch`。
- Live replay（本机私有样本集）：`python3 scripts/collect_inventory_live_metrics.py` 会在 `qa_metrics/inventory_live_metrics_summary.json` 中写入同样字段。

---

## 三、安全左移 (Security-Shift-Left)

### 规则3.1: 敏感信息必须脱敏

**要求**: 所有日志、输出、持久化数据必须脱敏敏感信息

```python
# ✅ 正确示例
from homework_agent.utils.observability import redact_url, _safe_value

# URL脱敏
safe_url = redact_url(url_with_token)

# 值脱敏
log_event(logger, "user_data",
          user_id=user_id,
          # _safe_value会自动处理敏感类型
          data=_safe_value(user_data))

# ❌ 错误示例
log_event(logger, "api_call", url=url_with_token)  # Token泄露
log_event(logger, "user_data", data=user_data)     # 可能包含PII
```

**必须脱敏的内容**:
```python
# URL参数
["access_token", "authorization", "token", "signature"]

# PII类型
chinese_id, chinese_phone, email, name, address

# 系统敏感
api_key, secret, password, private_key
```

**检查清单**:
- [ ] URL使用 `redact_url()` 处理
- [ ] 用户数据使用 `_safe_value()` 处理
- [ ] 日志不包含明文密码/Token

---

### 规则3.2: 外部输入必须验证

**要求**: 所有外部输入（用户上传、API响应）必须验证

```python
# ✅ 正确示例
def process_user_upload(file_data: bytes):
    """处理用户上传"""
    # 1. 验证文件类型
    if not is_valid_image(file_data):
        raise ValidationError("Invalid file type")

    # 2. 验证文件大小
    if len(file_data) > MAX_FILE_SIZE:
        raise ValidationError("File too large")

    # 3. 验证内容（病毒扫描等）
    if not scan_file(file_data):
        raise SecurityError("Malicious file detected")

    # 处理文件
    return process_image(file_data)

# ❌ 错误示例
def process_user_upload(file_data: bytes):
    # 直接处理，无验证
    return process_image(file_data)
```

**检查清单**:
- [ ] 文件上传验证类型和大小
- [ ] URL参数验证格式和范围
- [ ] API响应验证结构和类型

---

### 规则3.3: 错误信息不泄露系统细节

**要求**: 返回给用户的错误信息不包含系统内部细节

```python
# ✅ 正确示例
try:
    result = call_external_api()
except APIError as e:
    logger.error("API call failed", error=str(e), traceback=traceback.format_exc())
    # 返回通用错误给用户
    return {
        "status": "error",
        "message": "服务暂时不可用，请稍后重试",
        "error_code": "SERVICE_UNAVAILABLE",
    }

# ❌ 错误示例
except APIError as e:
    # 泄露内部错误和堆栈
    return {
        "status": "error",
        "message": str(e),  # 可能包含API密钥、内部路径
        "traceback": traceback.format_exc(),
    }
```

**检查清单**:
- [ ] 异常捕获后记录详细日志
- [ ] 用户友好的通用错误消息
- [ ] 错误代码用于技术排查

---

## 四、版本可追溯 (Version Traceability)

### 规则4.1: Prompt变更必须版本化

**要求**: 所有Prompt模板变更必须记录版本和变更原因

```yaml
# homework_agent/prompts/math_grader_system.yaml
id: math_grader_system
version: 2
language: zh
purpose: grade_math

template: |
  ...
```

**变更流程**:
```bash
# 1) 编辑 `homework_agent/prompts/<name>.yaml`，提升 `version` 字段
# 2) 在 PR 描述中写清：变更原因 + 预期影响 + 对应 replay 样本/指标
git commit -m "chore(prompts): bump <name> version - <reason>"
```

**检查清单**:
- [ ] Prompt文件头部有版本号
- [ ] 版本索引已更新
- [ ] Commit message包含版本和变更原因

---

### 规则4.2: Tool Schema必须稳定

**要求**: Tool接口变更必须考虑向后兼容

```python
# ✅ 正确示例：版本化Tool
@tool(version="1.0")
def diagram_slice(image: str, prefix: str) -> dict:
    """
    切分图示区域

    Args:
        image: 图像URL
        prefix: 切片保存路径前缀

    Returns:
        dict: {
            "status": "ok" | "error",
            "urls": {"figure_url": str, "question_url": str},
            "warnings": List[str],
        }
    """
    pass

# 升级到v2.0时保持兼容
@tool(version="2.0")
def diagram_slice_v2(image: str, prefix: str, *, _version: str = "2.0") -> dict:
    """
    v2.0新增参数：
    - compression_level: 压缩级别（0-9）
    - return_coords: 是否返回坐标

    v1.0调用自动适配
    """
    pass

# ❌ 错误示例：直接修改现有接口
def diagram_slice(image: str, prefix: str, compression_level: int = 5):
    # 破坏了现有调用方
    pass
```

**检查清单**:
- [ ] Tool有明确的版本号
- [ ] 新版本保持向后兼容
- [ ] 废弃的Tool有过渡期

---

### 规则4.3: 配置变更必须可审计

**要求**: 所有配置变更必须有审计日志

```python
# ✅ 正确示例
def update_config(key: str, value: Any, author: str):
    """更新配置"""
    old_value = get_config(key)

    # 记录变更
    log_event(logger, "config_change",
              key=key,
              old_value=str(old_value),
              new_value=str(value),
              author=author,
              timestamp=time.time(),
              git_commit=get_git_commit())

    # 应用变更
    set_config(key, value)

# ❌ 错误示例
def update_config(key: str, value: Any):
    # 无审计记录
    set_config(key, value)
```

**检查清单**:
- [ ] 配置变更记录before/after值
- [ ] 记录变更人和时间
- [ ] 关联Git commit

---

## 五、变更可回滚 (Rollback-Ready)

### 规则5.1: 部署必须包含回滚方案

**要求**: 每次部署必须预先定义回滚步骤

```yaml
# deployment.yml (部署清单)
deployment:
  version: v1.2.0
  date: 2025-01-15
  rollback_to: v1.1.0

  deployment_steps:
    - step: "构建Docker镜像"
      command: "<按项目部署形态填写：Docker/K8s/Serverless>"

    - step: "部署到Staging"
      command: "<按项目部署形态填写：staging deploy>"

    - step: "运行验证测试"
      command: "python3 -m pytest homework_agent/tests -v"

    - step: "部署到Production (Canary 5%)"
      command: "<按项目部署形态填写：production deploy (可选 canary)>"

  rollback_steps:
    - step: "回滚到上一个版本"
      command: |
        # 最小可用回滚策略（推荐先做这个）：
        # 1) git revert 引入问题的提交
        # 2) 走同一条 CI/CD 流水线重新部署
        #
        # 如果未来采用 K8s/Serverless/Feature Flag，可在此补充具体命令

    - step: "验证回滚成功"
      command: "<按项目部署形态填写：healthcheck/smoke>"

    - step: "通知团队"
      command: "send_alert 'Rollback completed'"
```

**检查清单**:
- [ ] 部署清单包含rollback_steps
- [ ] 回滚步骤已测试
- [ ] 回滚后可验证成功

---

### 规则5.2: 数据库变更必须可逆

**要求**: 数据库Schema变更必须提供回滚脚本

```sql
-- migrations/001_add_user_id.sql
-- 版本: 001
-- 描述: 添加user_id字段支持多租户

-- Up Migration (应用变更)
ALTER TABLE sessions ADD COLUMN user_id VARCHAR(64);
CREATE INDEX idx_sessions_user_id ON sessions(user_id);

-- Down Migration (回滚变更)
DROP INDEX IF EXISTS idx_sessions_user_id;
ALTER TABLE sessions DROP COLUMN IF EXISTS user_id;
```

```python
# migrations/migration_runner.py
class Migration001(Migration):
    """添加user_id字段"""

    def up(self):
        """应用变更"""
        self.db.execute("ALTER TABLE sessions ADD COLUMN user_id VARCHAR(64)")

    def down(self):
        """回滚变更"""
        self.db.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS user_id")
```

**检查清单**:
- [ ] 每个migration有up()和down()方法
- [ ] down()方法已测试
- [ ] 变更对现有数据无破坏性影响

---

### 规则5.3: Feature Flag支持动态开关

**要求**: 新功能应支持通过配置动态开关

```python
# homework_agent/features/flags.py
from homework_agent.utils.settings import get_settings

class FeatureFlags:
    """功能开关"""

    @staticmethod
    def is_enabled(feature_name: str, default: bool = False) -> bool:
        """检查功能是否启用"""
        settings = get_settings()
        flags = getattr(settings, "feature_flags", {})
        return flags.get(feature_name, default)

# 使用示例
def new_feature_logic():
    """新功能逻辑"""
    if not FeatureFlags.is_enabled("new_xyz_feature"):
        # 功能未启用，走原有逻辑
        return legacy_logic()

    # 新功能逻辑
    return improved_logic()

# 配置文件
# config/features.yaml
feature_flags:
  new_xyz_feature: false  # 默认关闭
  enable_telemetry: true  # 默认开启
```

**检查清单**:
- [ ] 新功能有Feature Flag控制
- [ ] Flag可通过配置文件动态修改
- [ ] Flag关闭时系统正常运行

---

## 六、PR提交检查清单

### 提交前自检

```markdown
## PR提交前检查

### 可观测性
- [ ] 新函数有 @trace_span 装饰器
- [ ] 关键事件有 log_event() 记录
- [ ] log_event 包含 session_id/request_id/iteration
- [ ] LLM调用记录了usage
- [ ] 敏感信息已脱敏

### 评估
- [ ] 新功能有replay测试用例
- [ ] 本地replay测试通过
- [ ] 评估数据可追溯（eval_id, git_commit）

### 安全
- [ ] 外部输入已验证
- [ ] 错误信息不泄露系统细节
- [ ] 日志不包含明文密码/Token

### 版本控制
- [ ] Prompt变更已版本化
- [ ] Tool Schema保持向后兼容
- [ ] 配置变更已审计

### 回滚
- [ ] 部署清单包含回滚步骤
- [ ] Database Migration有down()方法
- [ ] 新功能有Feature Flag
```

### Code Review模板

```markdown
## Agent开发PR Review

### 1. 可观测性检查
- [ ] @trace_span 使用正确
- [ ] log_event 包含必需字段
- [ ] Token使用已记录

### 2. 评估检查
- [ ] Replay测试用例充分
- [ ] Metrics报告无回归

### 3. 安全检查
- [ ] 敏感信息已脱敏
- [ ] 输入验证完整

### 4. 版本控制
- [ ] Prompt版本已更新
- [ ] 向后兼容性保持

### 5. 回滚准备
- [ ] 回滚步骤清晰
- [ ] Migration可逆

## 整体评估
- [ ] 批准合并
- [ ] 需要修改
```

---

## 七、CI集成

### 质量门禁Workflow

```yaml
# 示例：建议新增 `.github/workflows/quality_gate.yml`（当前仓库已包含 `.github/workflows/ci.yml` 的基础检查）
name: Agent Quality Gate

on:
  pull_request:
    branches: [main, dev]

jobs:
  quality_check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # 1. 单元测试
      - name: Unit Tests
        run: python3 -m pytest homework_agent/tests/ -v

      # 2. 可观测性检查
      - name: Observability Check
        run: |
          python3 scripts/check_observability.py
          # 检查: 新函数是否有@trace_span

      # 3. 安全扫描
      - name: Security Scan
        run: |
          bandit -r homework_agent/
          pylint --disable=all --enable=E0602 homework_agent/

      # 4. Replay评估
      - name: Replay Evaluation
        run: |
          python3 -m pytest homework_agent/tests/test_replay.py -v
          python3 scripts/collect_replay_metrics.py --output qa_metrics/metrics.json

          # Optional: Live metrics (requires real images + provider secrets)
          # python3 homework_agent/scripts/collect_metrics.py \
          #   --image-dir homework_agent/tests/replay_data/images \
          #   --mode local \
          #   --output qa_metrics/live_metrics.json

          # (P2) Reports for review/weekly tracking (CI artifacts)
          python3 scripts/generate_metrics_report.py --input qa_metrics/metrics_summary.json --output qa_metrics/report.html
          python3 scripts/generate_weekly_report.py \
            --inputs .github/baselines/metrics_baseline.json qa_metrics/metrics_summary.json \
            --metrics qa_metrics/metrics.json \
            --output qa_metrics/weekly.html

      # 5. 回归检测
      - name: Regression Check
        run: |
          python3 scripts/check_baseline.py \
            --current qa_metrics/metrics_summary.json \
            --baseline .github/baselines/metrics_baseline.json \
            --threshold 0.05
```

---

## 八、常用脚本

### 检查脚本模板

仓库已内置（建议直接调用脚本，而不是复制粘贴模板实现）：
- `scripts/check_observability.py`：静态扫描 `print()` / `log_event` 关键字段（best-effort）
- `scripts/check_baseline.py`：对比 `metrics_summary.json` 与 baseline（回归门禁）

---

## 九、常见问题

### Q1: 小功能也需要@trace_span吗？

**A**: 需要。可观测性是全有或全无的，只有全面覆盖才能保证生产可调试性。即使是小函数，Span开销也很小（微秒级）。

### Q2: Replay Dataset需要多少样本？

**A**:
- **最小（P0）**: 5-10个覆盖核心场景
- **推荐（P1）**: 20-30个覆盖边界情况
- **完整（P2）**: 50+个覆盖长尾场景

### Q3: 如何处理敏感测试数据？

**A**:
1. 使用合成数据或脱敏数据
2. 将真实图片存储在安全位置（如加密S3）
3. Prompt中明确标注"仅用于测试"

### Q4: Feature Flag会不会增加复杂度？

**A**: 短期会增加少量复杂度，但长期收益巨大：
- 快速回滚能力
- A/B测试能力
- 渐进式发布能力

建议从第一天就使用Feature Flag。

---

## 十、参考资源

### 项目文档
- [Agent架构分析](../agent/agent_architecture_analysis.md)
- [Agent质量分析](../agent/agent_quality_analysis.md)
- [原型到生产分析](../agent/prototype_to_production_analysis.md)

### 工具文档
- [Replay Dataset说明](../../docs/qa_replay_dataset.md)
- [可观测性工具](../../homework_agent/utils/observability.py)
- [Telemetry收集](../../homework_agent/utils/telemetry.py)

### 外部参考
- Google Agent白皮书系列
- OpenTelemetry Python SDK
- Prometheus Best Practices

---

**文档版本**: v1.0
**最后更新**: 2025年12月
**维护者**: Agent开发团队
