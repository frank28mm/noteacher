import base64
import uuid
import mimetypes
import os
import gradio as gr

from homework_agent.services.vision import VisionClient, VisionProvider
from homework_agent.services.llm import LLMClient
from homework_agent.models.schemas import ImageRef


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _estimate_base64_size(b64: str) -> int:
    return int(len(b64) * 0.75)


def format_grading_result(result) -> str:
    md = f"## 📊 评分结果\n\n"
    md += f"**科目 (Subject)**: {result.subject.value}\n\n"
    md += f"**摘要 (Summary)**: {result.summary}\n\n"

    if result.wrong_items:
        md += "### ❌ 错题列表\n"
        for idx, item in enumerate(result.wrong_items, 1):
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
    return md


def grade_homework_logic(img_path, img_url, subject, provider):
    """同步逻辑，供 Gradio 触发"""
    # gr.File returns path string or object with .name
    if hasattr(img_path, "name"):
        img_path = img_path.name

    if not img_path and not img_url:
        return "**错误**：请上传图片文件或提供公网 URL。", None, []

    use_url = bool(img_url)
    if provider == "doubao" and not use_url:
        return "**错误**：Doubao 只支持公网 URL。请填写 URL。", None, []

    try:
        img_refs = []
        if use_url:
            img_refs.append(ImageRef(url=img_url.strip()))
        else:
            b64 = _encode_image(img_path)
            if _estimate_base64_size(b64) > 20 * 1024 * 1024:
                return "**错误**：文件超过 20MB，请改用 URL。", None, []
            if provider != "qwen3":
                return "**错误**：当前仅 Qwen3 支持 base64 兜底，请使用 URL 或切换 Qwen3。", None, []
            # mime, _ = mimetypes.guess_type(img_path)
            # mime = mime or "image/jpeg"
            # DEBUG: Force JPEG to rule out mime issues
            mime = "image/jpeg"
            
            data_uri = f"data:{mime};base64,{b64}"
            print(f"DEBUG: Generated Data URI head: {data_uri[:50]}...")
            img_refs.append(ImageRef(base64=data_uri))

        vis = VisionClient()
        vision_provider = VisionProvider.QWEN3 if provider == "qwen3" else VisionProvider.DOUBAO
        ocr_result = vis.analyze(images=img_refs, provider=vision_provider)

        llm = LLMClient()
        if subject == "math":
            grade_result = llm.grade_math(ocr_result.text, provider="silicon" if provider == "qwen3" else "ark")
        elif subject == "english":
            grade_result = llm.grade_english(ocr_result.text, provider="silicon" if provider == "qwen3" else "ark")
        else:
            return f"**错误**：暂不支持学科 {subject} 的演示。", None, []

        md = format_grading_result(grade_result)
        options = [f"{i}:{item.get('reason','N/A')[:30]}" for i, item in enumerate(grade_result.wrong_items)]
        return md, grade_result, options
    except Exception as e:
        err_msg = str(e)
        if "20040" in err_msg:
            err_msg += " (提示：模型无法下载该 URL，建议用本地上传或可直连的 CDN/OSS URL)"
        return f"**系统错误**：{err_msg}", None, []


def tutor_chat_logic(message, history, grade_result, selected_items):
    history = history or []
    if not grade_result:
        response = "请先在【智能批改】标签页完成批改，我需要基于错题来辅导。"
        history.append([message, response])
        return "", history

    try:
        if len(history) >= 5:
            history.append([message, "已达到 5 轮上限，建议重新开始。"])
            return "", history

        items = grade_result.wrong_items
        if selected_items:
            indices = []
            for s in selected_items:
                try:
                    idx = int(s.split(":", 1)[0])
                    indices.append(idx)
                except Exception:
                    continue
            items = [grade_result.wrong_items[i] for i in indices if 0 <= i < len(grade_result.wrong_items)]

        context = {"summary": grade_result.summary, "wrong_items": items}

        llm = LLMClient()
        tutor_result = llm.socratic_tutor(
            question=message,
            wrong_item_context=context,
            session_id=f"demo_{uuid.uuid4().hex[:8]}",
            interaction_count=len(history),
            provider="silicon",
        )

        assistant_msg = tutor_result.messages[0]["content"] if tutor_result.messages else "无响应"
        history.append([message, assistant_msg])
        return "", history
    except Exception as e:
        history.append([message, f"系统错误：{e}"])
        return "", history


def create_demo():
    with gr.Blocks(title="作业检查大师 (Homework Agent)") as demo:
        gr.Markdown("# 🎓 作业检查大师 (Homework Agent)\nURL 优先（禁止 localhost/127/内网，单文件≤20MB）。Doubao 仅支持 URL；Qwen3 支持 URL 或 Base64 兜底。")

        with gr.Tabs():
            with gr.Tab("📝 智能批改"):
                with gr.Row():
                    with gr.Column(scale=1):
                        input_img = gr.File(label="上传图片 (File Upload)", file_types=["image"], height=300)
                        input_url = gr.Textbox(label="或输入公网 URL", placeholder="https://...", lines=1)
                        subject_dropdown = gr.Dropdown(choices=["math", "english"], value="math", label="学科 (Subject)")
                        provider_dropdown = gr.Dropdown(choices=["qwen3", "doubao"], value="qwen3", label="模型 (Provider)")
                        grade_btn = gr.Button("开始批改", variant="primary")
                    with gr.Column(scale=1):
                        output_md = gr.Markdown(label="批改结果")
                        raw_result_state = gr.State()
                        wrong_item_options = gr.State()

                grade_btn.click(
                    fn=grade_homework_logic,
                    inputs=[input_img, input_url, subject_dropdown, provider_dropdown],
                    outputs=[output_md, raw_result_state, wrong_item_options],
                )

            with gr.Tab("👩‍🏫 苏格拉底辅导"):
                gr.Markdown("基于批改结果进行辅导，可选择错题。最多 5 轮。")
                chatbot = gr.Chatbot(label="辅导对话", height=400)
                select_items = gr.CheckboxGroup(label="选择要讨论的错题", choices=[])
                msg = gr.Textbox(label="你的问题", placeholder="这道题为什么错了？")
                clear_btn = gr.Button("清除历史")

                def update_choices(opts):
                    return gr.update(choices=opts)

                raw_result_state.change(fn=update_choices, inputs=wrong_item_options, outputs=select_items)

                msg.submit(
                    fn=tutor_chat_logic,
                    inputs=[msg, chatbot, raw_result_state, select_items],
                    outputs=[msg, chatbot],
                )
                clear_btn.click(lambda: None, None, chatbot, queue=False)

        gr.Markdown("""
        ---
        注意：演示版直连模型（Qwen3/Doubao）。推荐使用公网 URL；Base64 仅用于小图兜底。
        """)
    return demo


if __name__ == "__main__":
    os.environ["no_proxy"] = "localhost,127.0.0.1,0.0.0.0"
    demo = create_demo()
    demo.queue().launch(server_name="127.0.0.1", server_port=7890, show_error=True)
