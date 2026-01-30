# 视觉模型配置说明

本文档描述视觉模型的可选项、配置方式及调用示例。当前仅向用户暴露 `doubao` 和 `qwen3` 两个选项，默认使用 `doubao`。不对外提供 OpenAI 视觉选项。

> 说明：统一阅卷 Agent 在 `/grade` 阶段完成视觉理解与批改；Chat 不直接调用视觉模型（只读取 `judgment_basis + vision_raw_text`）。

## 1. 供应商与白名单
- `doubao`: 火山方舟平台，模型名 `doubao-seed-1-6-vision-250815`
- `qwen3`: SiliconFlow 平台，模型名 `Qwen/Qwen3-VL-32B-Thinking`

请求字段 `vision_provider` 仅接受上述白名单值；未指定时默认 `doubao`。后端需验证白名单，禁止任意 base_url/model 注入。

## 2. 环境变量
```env
# SiliconFlow (qwen3)
SILICON_API_KEY=slk-xxxxxxxxxxxxxxxxxxxxxxxx
SILICON_BASE_URL=https://api.siliconflow.cn/v1
SILICON_VISION_MODEL=Qwen/Qwen3-VL-32B-Thinking

# 火山方舟 (doubao)
ARK_API_KEY=ark-xxxxxxxxxxxxxxxxxxxxxxxx
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_VISION_MODEL=doubao-seed-1-6-vision-250815

# QIndex Locator（题号+bbox，bbox-only）
# - 若模型名以 doubao- 开头，locator 走 Ark（responses.create）
ARK_QINDEX_MODEL=doubao-seed-1-6-vision-250815
```

## 3. 调用示例

### 3.1 SiliconFlow（OpenAI 兼容 Chat Completions）
```python
from openai import OpenAI

client = OpenAI(
    base_url="https://api.siliconflow.cn/v1",
    api_key="SILICON_API_KEY"
)

resp = client.chat.completions.create(
    model="Qwen/Qwen3-VL-32B-Thinking",
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请识别这道题目的题干和答案区域"},
                {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
            ]
        }
    ]
)
```

### 3.2 火山方舟（OpenAI SDK，input_image/input_text）
```python
from openai import OpenAI

client = OpenAI(
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key="ARK_API_KEY",
)

resp = client.responses.create(
    model="doubao-seed-1-6-vision-250815",
    input=[
        {
            "role": "user",
            "content": [
                {"type": "input_image", "image_url": "https://example.com/image.jpg"},
                {"type": "input_text", "text": "你看见了什么？"}
            ],
        }
    ]
)
```

> 注意：不同供应商对图片字段格式略有差异（silicon 使用 `image_url`；方舟示例使用 `input_image`），实现时需按 provider 适配 payload。

## 4. 选择策略
- 请求字段：`vision_provider` = `doubao` | `qwen3`，默认 `doubao`。
- 模型/endpoint：后端按 provider 选择对应 `base_url`/`model`/`api_key`，不允许客户端自定义 base_url。
- 失败回退：可按需要配置 fallback（例如 doubao → qwen3），但需在实现中显式定义。

## 5. 注意事项（URL First）
- 优先使用公网 HTTP/HTTPS URL，禁止 localhost/127/内网；单文件不超过 5 MB（可配置 `MAX_UPLOAD_IMAGE_BYTES`）。
- Doubao 对外输入优先用 URL；后端在遇到“供应商抓 URL 超时/不稳定”时，会走内部兜底：先后端下载图片→转 data-url(base64)→直接喂给 Doubao（绕开对方抓 URL）。
- Qwen3 支持 URL（推荐）或 Base64 兜底；Doubao 的 base64 仅接受 data URL 形态（`data:image/...;base64,...`，用于后端内部兜底，不建议客户端直接使用）。
- 不要将真实 API Key 提交到仓库；运行前在 `.env` 设置。
- 确认 `base_url` 与 provider 一致，避免调用默认 openai.com。
- 确保限流与重试策略按契约执行（幂等键、防重复）。 
