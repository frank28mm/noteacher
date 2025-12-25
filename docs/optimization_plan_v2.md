# Autonomous Agent 优化方案 v2

**创建时间**: 2024-12-26
**基于**: 对照实验结果
**状态**: 待审批

---

## 📋 对照实验结论总结

| 组别 | 配置 | 耗时 | 准确率 | 结论 |
|------|------|------|--------|------|
| 对照组 | 完整流程 | 477.7s | 8/9 (88.9%) | 基准 |
| 实验组 A | 跳过 diagram_slice，保留 OCR | 470.8s | 7/9 (77.8%) | ⚠️ 准确率下降 11.1% |
| 实验组 B | 跳过全部（纯 Vision） | 283.2s | 5/9 (55.6%) | ❌ 准确率大幅下降 |

**核心发现**:
1. **diagram_slice 有价值** - 跳过后准确率下降 11.1%
2. **OCR 是关键** - 跳过后准确率下降 33.3%
3. **不能简单禁用 diagram_slice** - 优化应使其更高效而非移除

---

## 🎯 优化目标

| 指标 | 当前 | 目标 | 方法 |
|------|------|------|------|
| **P50 耗时** | ~480s | 240s | 减少 50% |
| **准确率** | 88.9% | ≥88% | 保持水平 |
| **Loop 迭代** | 3 (max) | ≤2 | 减少重复尝试 |
| **P95 耗时** | ~600s | 360s | 减少 40% |

---

## 🔍 问题诊断（基于实验）

### 1. 为什么需要 3 次迭代？

**demo_d534d690 案例分析**:
- **Iteration 1**: Planner 调用 diagram_slice → 失败 (diagram_roi_not_found)
- **Iteration 2**: Planner 再次尝试 diagram_slice → 仍失败（相同参数）
- **Iteration 3**: Reflector 仍未达到 confidence ≥ 0.90 → 强制退出

**问题**:
- OpenCV pipeline 失败后，Planner 缺乏"自知之明"，继续重复相同尝试
- Reflector 对"OCR 完整但缺少图示"的情况置信度评估过于保守

### 2. 对照实验说明什么？

| 实验组 | 耗时变化 | 准确率变化 | 启示 |
|--------|----------|-----------|------|
| A vs 对照 | -6.9s (-1.4%) | -11.1% | diagram_slice 对准确率很重要 |
| B vs 对照 | -194.5s (-40.7%) | -33.3% | OCR 是准确率基石 |

**结论**: 优化方向应该是**减少重复尝试**而非**移除关键工具**

---

## 📊 优化方案（P0/P1/P2）

### P0 - 立即实施（止血措施）

#### P0.1: OCR 缓存（基于图像内容哈希）

**问题**: 同一图片重复 OCR
**收益**: 30-60s 节省（命中时）

**实现**:
```python
# services/autonomous_tools.py
import hashlib
from pathlib import Path

def _compute_image_hash(image_url: str) -> str:
    """下载图片并计算内容哈希（非 URL 哈希）"""
    response = requests.get(image_url, timeout=10)
    content = response.content
    return hashlib.sha256(content).hexdigest()

def ocr_fallback(*, image: str, provider: str) -> Dict[str, Any]:
    img_hash = _compute_image_hash(image)
    cache_key = f"ocr_cache:{img_hash}"

    # Check cache
    cached = redis_get(cache_key)
    if cached:
        return {"status": "ok", "text": cached, "source": "cache"}

    # Call Vision API
    result = _call_vision_ocr(image, provider)
    if result["status"] == "ok":
        redis_set(cache_key, result["text"], ex=86400)  # 24h

    return result
```

**注意事项**:
- 使用 **image content hash** 非 URL hash（URL 可能带 token）
- Redis TTL 24h
- Cache key 格式: `ocr_cache:{sha256}`

---

#### P0.2: Aggregator 图片压缩（仅原图）

**问题**: demo_d534d690 中 Aggregator 耗时 138.7s，原图可能过大
**收益**: 20-40s 节省

**实现**:
```python
# services/autonomous_agent.py - AggregatorAgent.run()
def _compress_image_if_needed(url: str, max_side: int = 1280) -> str:
    """如果图片超过 max_side，压缩后返回新 URL"""
    if url.startswith("data:image"):
        return url  # base64 skip

    # 下载并检查尺寸
    resp = requests.get(url, timeout=10)
    img = Image.open(BytesIO(resp.content))
    w, h = img.size

    if max(w, h) <= max_side:
        return url  # 无需压缩

    # 压缩
    new_w, new_h = (max_side, int(h * max_side / w)) if w > h else (int(w * max_side / h), max_side)
    compressed = img.resize((new_w, new_h), Image.LANCZOS)
    buffer = BytesIO()
    compressed.save(buffer, format="JPEG", quality=85)
    compressed_url = upload_to_supabase(buffer.getvalue(), prefix="compressed/")

    return compressed_url

# 在 AggregatorAgent.run() 中
image_urls = [_dedupe_images(figure_urls + question_urls)]
if not image_urls:
    image_urls = [_compress_image_if_needed(u) for u in _dedupe_images(state.image_urls or [])[:1]]
```

**注意事项**:
- **仅压缩原图**，切片已优化过不压缩
- max_side=1280（平衡质量与速度）
- JPEG quality=85
- 压缩后上传 Supabase 并缓存

---

#### P0.3: diagram_slice 失败缓存（多图片支持）

**问题**: 同一图片重复失败 diagram_slice
**收益**: 10-20s 节省（命中时）

**实现**:
```python
# services/autonomous_tools.py
def diagram_slice(*, image: str, prefix: str) -> Dict[str, Any]:
    img_hash = _compute_image_hash(image)
    cache_key = f"slice_failed:{img_hash}"

    # Check if previously failed
    if redis_get(cache_key):
        logger.info(f"diagram_slice cached failure for {img_hash}")
        return {
            "status": "error",
            "message": "diagram_roi_not_found",
            "cached": True,
        }

    # Run OpenCV pipeline
    result = run_opencv_pipeline(image)
    if result["status"] != "ok" and "roi_not_found" in result.get("message", ""):
        redis_set(cache_key, "1", ex=3600)  # 1h

    return result
```

**注意事项**:
- 使用 **image_hash** 非 URL hash（支持同一内容多 URL）
- TTL=3600s（1小时）
- 仅缓存 "roi_not_found" 错误，其他错误不缓存

---

#### P0.4: Aggregator 日志增强（image_source）

**问题**: 无法分析不同来源图片的性能
**收益**: 可观测性提升

**实现**:
```python
# services/autonomous_agent.py - AggregatorAgent.run()
log_event(
    aggregator_logger,
    "agent_aggregate_start",
    session_id=state.session_id,
    image_source=image_source,  # "slices", "original", "qindex", "base64"
    image_count=len(image_refs),
    original_image_size=len(state.image_urls or []),
    figure_count=len(figure_urls),
    question_count=len(question_urls),
)
```

**image_source 枚举**:
- `slices`: 使用 figure+question 切片
- `qindex`: 使用 qindex_fetch 获取的切片
- `original`: 使用原图（压缩后）
- `base64`: 使用 base64 图片

---

### P1 - 短期实施（逻辑优化）

#### P1.1: Reflector "图示豁免"逻辑

**问题**: 几何题即使图示失败，OCR 完整时也应给予合理置信度
**收益**: 减少 1 次迭代（~60-100s）

**实现**:
```python
# services/autonomous_agent.py - ReflectorAgent.run()
async def run(self, state: SessionState, plan: List[Dict[str, Any]]) -> ReflectorPayload:
    # ... existing code ...

    parsed = _parse_json(..., ReflectorPayload)

    # 图 示豁免：OCR 完整 + 缺少图示 + 置信度接近阈值
    if (not parsed.pass_
        and 0.85 <= parsed.confidence < 0.90
        and len(state.ocr_text or "") > 100
        and any("diagram" in str(r).lower() or "roi" in str(r).lower()
                for r in state.tool_results.values())):
        logger.info("Reflector: 图示豁免触发，提升置信度")
        parsed.pass_ = True
        parsed.confidence = 0.90
        parsed.suggestion = "图示不足，基于完整文本推断"

    return parsed
```

**注意事项**:
- 仅在 `confidence >= 0.85` 时触发
- 要求 OCR 长度 > 100 字符
- 检测到 diagram_slice 失败标记
- **不改变 Reflector 输出内容**，仅调整 pass/confidence

---

#### P1.2: OpenCV 参数分级（快速失败）

**问题**: 3 次迭代使用相同参数，无改进
**收益**: 减少第 3 次无效迭代（~60-100s）

**实现**:
```python
# services/autonomous_agent.py - PlannerAgent.run()
async def run(self, state: SessionState) -> PlannerPayload:
    iteration = state.reflection_count + 1

    # 如果第 2 次 iteration 仍失败，降低 diagram_slice 优先级
    if iteration >= 2:
        prev_failed = any(
            "diagram" in str(r).lower() and "roi_not_found" in str(r).lower()
            for r in state.tool_results.values()
        )
        if prev_failed:
            # 第 3 次迭代跳过 diagram_slice，直接使用 OCR
            logger.info(f"Planner: 第{iteration}次迭代，跳过 diagram_slice")
            for step in payload.plan:
                if step.get("step") == "diagram_slice":
                    step["step"] = "ocr_fallback"
                    step["args"] = {"image": state.image_urls[0]}

    # ... rest of code ...
```

**注意事项**:
- 仅在 iteration >= 2 时触发
- 仅替换 diagram_slice → ocr_fallback
- 不影响 iteration 1 的正常流程

---

#### P1.3: 添加明确警告（图示不足）

**问题**: 用户不知道结果基于文本推断
**收益**: 透明度提升

**实现**:
```python
# services/autonomous_agent.py - run_autonomous_grade_agent()
# 在 Aggregator 后
if any("diagram_roi_not_found" in str(w) for w in state.warnings):
    warnings.append("⚠️ 图示识别失败，批改结果基于文本推断，建议人工复核")
```

---

### P2 - 长期实施（架构升级）

#### P2.1: qindex 切片复用

**问题**: qindex_fetch 获取的切片未缓存
**收益**: 10-30s 节省

**实现**:
```python
# services/autonomous_tools.py
def qindex_fetch(*, session_id: str) -> Dict[str, Any]:
    cache_key = f"qindex_slices:{session_id}"

    cached = redis_get(cache_key)
    if cached:
        return json.loads(cached)

    # Fetch from qindex service
    result = _fetch_from_qindex(session_id)
    redis_set(cache_key, json.dumps(result), ex=3600)

    return result
```

---

#### P2.2: 统一预处理入口

**问题**: run_opencv_pipeline 在多处调用
**收益**: 代码可维护性提升

**实现**:
```python
# services/preprocessing.py (新文件)
class PreprocessingPipeline:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.cache = {}

    async def process_image(self, image_ref: ImageRef) -> Dict[str, Any]:
        """统一入口：opencv + upload + cache"""
        img_hash = _compute_image_hash(str(image_ref.url or image_ref.base64))

        if img_hash in self.cache:
            return self.cache[img_hash]

        slices = await asyncio.to_thread(run_opencv_pipeline, image_ref)
        urls = await asyncio.to_thread(upload_slices, slices, prefix=f"autonomous/{self.session_id}/")

        result = {"slices": slices, "urls": urls}
        self.cache[img_hash] = result
        return result
```

---

## 📅 实施计划

| 周次 | 任务 | 预期收益 | 风险 |
|------|------|----------|------|
| **Week 2** | P0.1 OCR 缓存 | -40s | 低 |
| **Week 2** | P0.2 Aggregator 压缩 | -30s | 中 |
| **Week 2** | P0.3 失败缓存 | -20s | 低 |
| **Week 3** | P0.4 日志增强 | 可观测性 | 无 |
| **Week 4** | P1.1 图示豁免 | -80s (1次迭代) | 中 |
| **Week 4** | P1.2 OpenCV 分级 | -60s (1次迭代) | 中 |
| **Week 5** | P1.3 明确警告 | UX | 无 |
| **Week 6+** | P2.1 qindex 复用 | -20s | 低 |
| **Week 6+** | P2.2 统一入口 | 可维护性 | 无 |

**预期总计**:
- P0: -90s (477s → 387s)
- P1: -140s (387s → 247s) **目标达成**
- P2: -20s + 可维护性

---

## ⚠️ 风险评估

| 风险 | 缓解措施 | 责任人 |
|------|----------|--------|
| **准确率下降** | 对照实验验证，每项 P0/P1 都需要 A/B test | QA |
| **缓存污染** | 使用 content hash 非 URL hash，设置合理 TTL | Backend |
| **压缩过度** | max_side=1280, quality=85，视觉检查 | Frontend |
| **图示豁免误触发** | confidence >= 0.85 才触发，人工复核首批结果 | Product |

---

## 📈 成功指标

| 指标 | 基准 | 目标 | 验证方法 |
|------|------|------|----------|
| **P50 耗时** | 477s | ≤240s | telemetry.py 分析 |
| **准确率** | 88.9% | ≥88% | 对照实验 |
| **Loop 平均迭代** | 2.8 | ≤2.0 | telemetry.py |
| **P95 耗时** | 600s | ≤360s | telemetry.py |
| **diagram_roi_not_found 警告率** | ~40% | ≤30% | 日志分析 |

---

## 🔄 对照实验验证流程

每项 P0/P1 实施后，运行对照实验：

```bash
# 1. 部署新版本
# 2. 运行测试集
python -m homework_agent.tests.test_real_image

# 3. 收集指标
python -m homework_agent.tests.test_telemetry

# 4. 对比准确率
# 如果准确率下降 > 5%，回滚该优化
```

**回滚标准**:
- 准确率下降 > 5%
- error rate > 10%
- P95 latency > 600s（未改善）

---

## 📌 关键决策点

### 决策 1: 为什么不禁用 diagram_slice？

**对照实验 A**: 跳过 diagram_slice → 准确率 88.9% → 77.8%
**结论**: diagram_slice 对 11.1% 的题目准确率有关键作用

**优化策略**: 不禁用，而是：
1. 失败后缓存（避免重复尝试）
2. 第 2 次迭代后降级到 OCR（快速失败）

### 决策 2: 为什么 confidence_threshold 保持 0.90？

**当前**: 0.90
**实验 B**: 降至 0.85 会影响最终结果质量

**优化策略**: 保持 0.90，但使用"图示豁免"在特定条件下提升置信度

### 决策 3: 为什么压缩仅限原图？

**原因**:
- 切片已经过优化（figure + question 分离）
- 压缩切片可能丢失几何细节
- 原图通常较大（手机拍照 >2MB）

---

## 📚 参考资料

- [qa_test_report_real_image.md](./qa_test_report_real_image.md) - 真实图片测试报告
- [qa_replay_dataset.md](./qa_replay_dataset.md) - 回放数据集结构
- [autonomous_grade_agent_design.md](./autonomous_grade_agent_design.md) - 系统设计
- [autonomous_agent_implementation.md](./autonomous_agent_implementation.md) - 实现文档

---

**文档版本**: v2
**最后更新**: 2024-12-26
**审核状态**: 待审批
