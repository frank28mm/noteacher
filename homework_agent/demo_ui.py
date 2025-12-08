"""作业检查大师 Demo UI
真实业务场景模拟：用户上传图片 → Supabase Storage → 公网 URL → 后端 API
"""
import os
import uuid
import mimetypes
import httpx
import gradio as gr
from dotenv import load_dotenv

from typing import List, Dict, Any, Optional
from homework_agent.models.schemas import Subject, VisionProvider, WrongItem, Message
from homework_agent.utils.supabase_client import get_storage_client


# 加载环境变量 - 使用脚本所在目录的父目录（项目根目录）
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

# API 基础 URL - 从环境变量读取，默认为本地
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/v1")


def upload_to_supabase(file_path: str, min_side: int) -> List[str]:
    """上传文件到 Supabase Storage 并返回公网 URL 列表

    支持：图片（含 HEIC/HEIF 自动转码），PDF（拆页最多 8 页转图片）。
    """
    if not file_path or not os.path.exists(file_path):
        raise ValueError("文件不存在")

    # 检查文件大小 (<20MB)
    file_size = os.path.getsize(file_path)
    if file_size > 20 * 1024 * 1024:
        raise ValueError(f"文件超过 20MB: {file_size / 1024 / 1024:.2f}MB")

    storage_client = get_storage_client()
    public_urls = storage_client.upload_files(file_path, prefix="demo/", min_side=min_side)

    return public_urls


def format_grading_result(result: Dict[str, Any]) -> str:
    """格式化批改结果为 Markdown"""
    md = f"## 📊 评分结果\n\n"
    md += f"**科目 (Subject)**: {result.get('subject', 'N/A')}\n\n"
    md += f"**摘要 (Summary)**: {result.get('summary', 'N/A')}\n\n"

    wrong_items = result.get('wrong_items', [])
    if wrong_items:
        md += "### ❌ 错题列表\n"
        for idx, item in enumerate(wrong_items, 1):
            md += f"**{idx}.** {item.get('question_content', 'N/A')}\n"
            md += f"- 错误原因: {item.get('reason', 'N/A')}\n"
            if item.get("analysis"):
                md += f"- 分析: {item.get('analysis')}\n"
            bbox = item.get("bbox")
            if bbox:
                md += f"- 位置 (BBox): `{bbox}`\n"
            md += "\n"
    else:
        md += "### ✅ 全对 (All Correct!)\n太棒了！没有发现错误。\n"

    if result.get('warnings'):
        md += "\n### ⚠️ 警告\n"
        for warning in result['warnings']:
            md += f"- {warning}\n"

    return md


async def call_grade_api(image_urls: List[str], subject: str, provider: str) -> Dict[str, Any]:
    """调用后端 /api/v1/grade API"""
    # 构建请求
    session_id = f"demo_{uuid.uuid4().hex[:8]}"
    payload = {
        "images": [{"url": u} for u in image_urls],
        "subject": subject,
        "session_id": session_id,
        "vision_provider": provider
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            f"{API_BASE_URL}/grade",
            json=payload
        )

    if response.status_code != 200:
        raise Exception(f"API 调用失败: {response.status_code} - {response.text}")

    return response.json()


async def call_chat_api(question: str, session_id: str, subject: str,
                       context_item_ids: Optional[List[str]] = None) -> str:
    """调用后端 /api/v1/chat API

    Args:
        question: 用户问题
        session_id: 会话 ID
        subject: 学科
        context_item_ids: 上下文错题 ID 列表

    Returns:
        助手回复
    """
    payload = {
        "history": [],
        "question": question,
        "subject": subject,
        "session_id": session_id,
        "context_item_ids": context_item_ids or []
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{API_BASE_URL}/chat",
            json=payload
        )

    if response.status_code != 200:
        raise Exception(f"API 调用失败: {response.status_code} - {response.text}")

    # 解析 SSE 响应 - 遍历事件，取最后一条 assistant 消息
    content = ""
    current_event = ""
    for line in response.text.split('\n'):
        line = line.strip()
        if line.startswith('event:'):
            current_event = line[6:].strip()
        elif line.startswith('data:'):
            data = line[5:].strip()
            if data and data != '{"status":"done"}':
                try:
                    import json
                    json_data = json.loads(data)
                    if current_event == 'chat' and 'messages' in json_data:
                        messages = json_data.get('messages', [])
                        # 反向查找最后一条助手消息
                        for msg in reversed(messages):
                            if msg.get("role") == "assistant":
                                content = msg.get("content", "")
                                break
                except Exception as e:
                    print(f"SSE parse error: {e}, data: {data}")
                    pass

    return content or "无响应"


async def grade_homework_logic(img_path, subject, provider):
    """批改作业的主逻辑"""
    # gr.File returns path string or object with .name
    if hasattr(img_path, "name"):
        img_path = img_path.name

    if not img_path:
        return "**错误**：请上传图片文件。", None, [], None

    try:
        # 尺寸下限：Qwen3 >=28px，Doubao >=14px
        min_side = 28 if provider == "qwen3" else 14

        # Step 1: 上传到 Supabase Storage
        gr.Info("📤 正在上传文件到云存储...")
        image_urls = upload_to_supabase(img_path, min_side=min_side)
        if not image_urls:
            return "**错误**：上传失败，未获取到 URL。", None, [], None
        gr.Info(f"✅ 文件已上传，共 {len(image_urls)} 张用于批改")

        # Step 2: 调用后端 API
        gr.Info("🤖 正在调用批改服务...")
        result = await call_grade_api(image_urls, subject, provider)

        # Step 3: 格式化结果
        formatted_md = format_grading_result(result)
        session_id = result.get('session_id')

        # Step 4: 准备错题选项
        wrong_items = result.get('wrong_items', [])
        options = [f"{i}:{item.get('reason', 'N/A')[:30]}" for i, item in enumerate(wrong_items)]

        gr.Info("✅ 批改完成！")
        return formatted_md, session_id, options, image_urls[0]

    except ValueError as e:
        return f"**错误**：{str(e)}", None, [], None
    except Exception as e:
        err_msg = str(e)
        if "20040" in err_msg:
            err_msg += "\n\n提示：模型无法下载该 URL，建议检查图片是否可公开访问"
        return f"**系统错误**：{err_msg}", None, [], None


async def tutor_chat_logic(message, history, session_id, selected_items, subject):
    """苏格拉底辅导逻辑"""
    history = history or []
    if not session_id:
        response = "请先在【智能批改】标签页完成批改，我需要基于错题来辅导。"
        history.append([message, response])
        return "", history

    if len(history) >= 5:
        history.append([message, "已达到 5 轮上限，建议重新开始。"])
        return "", history

    try:
        # 解析选中的错题索引
        context_item_ids = []
        if selected_items:
            for s in selected_items:
                try:
                    idx = int(s.split(":", 1)[0])
                    context_item_ids.append(idx)
                except:
                    pass

        gr.Info("🤔 正在思考...")
        assistant_msg = await call_chat_api(
            question=message,
            session_id=session_id,
            subject=subject,
            context_item_ids=context_item_ids
        )

        history.append([message, assistant_msg])
        return "", history

    except Exception as e:
        history.append([message, f"系统错误：{str(e)}"])
        return "", history


def create_demo():
    """创建 Gradio Demo"""
    with gr.Blocks(title="作业检查大师 (Homework Agent)") as demo:
        gr.Markdown("""
        # 🎓 作业检查大师 (Homework Agent)

        ### 🔄 真实业务场景模拟
        - **Step 1**: 上传本地图片 → Supabase Storage (云存储)
        - **Step 2**: 获取公网 URL
        - **Step 3**: 调用后端 `/api/v1/grade` 进行批改
        - **Step 4**: 调用后端 `/api/v1/chat` 进行苏格拉底辅导

        ### 📝 使用说明
        - ✅ 支持格式：JPG、PNG、WebP
        - 🗂️ 支持：HEIC/HEIF 自动转 JPEG，PDF 自动拆前 8 页
        - ⚠️ 文件大小：≤ 20MB
        - 📐 尺寸：Qwen3 最小边 ≥28px，Doubao 最小边 ≥14px
        - 🌍 URL 要求：必须是公网可访问 (禁止 localhost/内网)
        - 🤖 模型选择：Qwen3 (支持 URL+base64) / Doubao (仅 URL)
        """)

        with gr.Tabs():
            # ========== Tab 1: 智能批改 ==========
            with gr.Tab("📝 智能批改"):
                with gr.Row():
                    with gr.Column(scale=1):
                        input_img = gr.File(
                            label="📤 上传图片",
                            file_types=["image"],
                            height=300
                        )
                        subject_dropdown = gr.Dropdown(
                            choices=["math", "english"],
                            value="math",
                            label="📚 学科 (Subject)"
                        )
                        provider_dropdown = gr.Dropdown(
                            choices=["qwen3", "doubao"],
                            value="qwen3",
                            label="🤖 模型 (Provider)"
                        )
                        grade_btn = gr.Button("🚀 开始批改", variant="primary")

                    with gr.Column(scale=1):
                        output_md = gr.Markdown(label="📊 批改结果")
                        session_id_state = gr.State()
                        wrong_item_options = gr.State()
                        image_url_state = gr.State()

                grade_btn.click(
                    fn=grade_homework_logic,
                    inputs=[input_img, subject_dropdown, provider_dropdown],
                    outputs=[output_md, session_id_state, wrong_item_options, image_url_state],
                )

            # ========== Tab 2: 苏格拉底辅导 ==========
            with gr.Tab("👩‍🏫 苏格拉底辅导"):
                gr.Markdown("基于批改结果进行启发式辅导，最多 5 轮对话。")

                chatbot = gr.Chatbot(label="💬 辅导对话", height=400)
                select_items = gr.CheckboxGroup(
                    label="✅ 选择要讨论的错题",
                    choices=[]
                )
                msg = gr.Textbox(
                    label="💭 你的问题",
                    placeholder="这道题为什么错了？应该怎么思考？"
                )
                clear_btn = gr.Button("🗑️ 清除历史")

                # 状态更新函数
                def update_choices(opts):
                    return gr.update(choices=opts)

                # 当错题选项变化时，更新选择列表
                wrong_item_options.change(
                    fn=update_choices,
                    inputs=wrong_item_options,
                    outputs=select_items
                )

                # 发送消息
                msg.submit(
                    fn=tutor_chat_logic,
                    inputs=[msg, chatbot, session_id_state, select_items, subject_dropdown],
                    outputs=[msg, chatbot],
                )

                # 清除历史
                clear_btn.click(
                    fn=lambda: ([], []),
                    inputs=None,
                    outputs=[chatbot, msg],
                    queue=False
                )

        gr.Markdown("""
        ---
        ### 🔧 技术架构
        - **前端**: Gradio (端口 7890)
        - **后端**: FastAPI (端口 8000)
        - **存储**: Supabase Storage (Public Bucket)
        - **模型**: Qwen3-VL (SiliconFlow) / Doubao-Vision (Ark)

        ### ⚡ 性能说明
        - 首次批改可能需要 30-60 秒 (模型推理时间)
        - 辅导对话响应较快 (5-10 秒)
        - 大图片 (>5MB) 建议使用 Qwen3 模型
        """)

    return demo


if __name__ == "__main__":
    # 设置环境变量
    os.environ["no_proxy"] = "localhost,127.0.0.1,0.0.0.0"

    # 创建并启动 Demo
    demo = create_demo()
    demo.queue().launch(
        server_name="127.0.0.1",
        server_port=7890,
        show_error=True
    )
