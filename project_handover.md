# 作业检查大师 - 项目交接文档

## 1. 项目目标
构建一个基于 **Anthropic Claude Agent SDK** 的智能作业检查 Agent。
- **核心功能**：自动识别数学/英语作业图片，判断对错，并给出批改建议。
- **技术栈**：Python, Claude Agent SDK, OpenCV (图像处理)。
- **关键指标**：识别准确率 > 95%。

## 2. 系统架构
- **`HomeworkAgent` 类** (`homework_agent.py`)：
    - 封装了 Claude Client。
    - 注册了自定义工具（Tools）。
    - 实现了 `check_homework` 主流程：观察 -> 思考 -> 调用工具 -> 输出 JSON。
- **图像处理工具**：
    - `crop_and_zoom`: 裁剪并放大模糊区域（基于 OpenCV）。
    - `enhance_image`: 图像二值化/去噪增强（基于 OpenCV）。
- **测试脚本**：
    - `test_agent.py`: 使用生成的 Dummy 图片测试基础流程。
    - `test_real_homework.py`: 使用真实图片 (`homework_img/`) 进行端到端测试。

## 3. 当前进度
- [x] **环境搭建**：依赖已安装 (`requirements.txt`)，API 连接已调通。
- [x] **核心代码实现**：Agent 类及 OpenCV 工具已完成。
- [x] **基础验证**：`test_agent.py` 运行通过，Agent 能调用工具并输出 JSON。
- [!] **真实场景验证**：正在进行中，遇到技术阻碍。

## 4. 遇到的问题与挑战
### 核心问题：图片传递机制
在尝试处理真实高清作业图片（如 iPhone 拍摄的 2MB+ 照片）时，遇到了 **SDK 客户端缓冲区限制**。

- **尝试方案 A (使用 SDK `Read` 工具)**：
    - **操作**：让 Agent 直接调用 `Read` 工具读取图片文件。
    - **结果**：**失败**。报错 `JSON message exceeded maximum buffer size of 1048576 bytes`。SDK 内部处理 Tool Result 时，Base64 编码后的图片字符串超过了 1MB 限制。
    
- **尝试方案 B (直接注入 Base64)**：
    - **操作**：在 Python 端预先读取图片转 Base64，通过 `client.query()` 发送。
    - **结果**：**失败**。SDK 的 `AsyncIterable` 消息格式较为复杂，多次尝试构造 `{"type": "image", ...}` 均被 SDK 拒绝或解析错误。

## 5. 拟定解决方案 (Next Steps)
我们决定采用 **方案 C：预处理压缩 + Read 工具**。

### 方案逻辑
既然直接读取大图会爆内存，直接注入格式又不对，最稳妥的方式是**减小图片体积**，使其适应 SDK 的限制。

### 具体执行计划
1. **修改 `homework_agent.py`**：
    - 新增 `preprocess_image(path)` 函数。
    - 使用 OpenCV 将图片长边缩放至 **1024px** 左右（通常 Base64 大小会控制在 300KB-500KB）。
    - 将压缩后的图片保存为临时文件（如 `_temp_resized.jpg`）。
2. **更新 Agent Prompt**：
    - 指示 Agent 读取这些**临时文件**的路径，而不是原始大图。
3. **验证**：
    - 运行 `test_real_homework.py`，确认不再报错且识别准确。

## 6. 关于图片质量的说明
用户担心压缩影响识别。
- **结论**：适度压缩（1024px）通常**不会**影响手写体识别。Claude 3.5 Sonnet 的视觉能力很强，只要文字清晰度保留，分辨率降低对语义理解影响微乎其微。
- **兜底策略**：如果发现特定模糊图片识别率下降，可以引入 `crop_and_zoom` 工具的**切片策略**（将大图切成几张小图分别识别），而不是整张压缩。

## 7. 常用命令
```bash
# 运行真实图片测试
python3 test_real_homework.py

# 查看 Agent 代码
cat homework_agent.py
```
