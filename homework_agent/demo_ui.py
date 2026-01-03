"""作业检查大师 Demo UI
真实业务场景模拟：用户上传文件 → 后端 /uploads → Supabase Storage → /grade(upload_id) → /chat
"""

import os
import uuid
import json
import mimetypes
import asyncio
import time
import re
import httpx
import gradio as gr
from dotenv import load_dotenv
import inspect
from contextlib import ExitStack

from typing import List, Dict, Any, Optional, AsyncGenerator, Tuple
from homework_agent.utils.settings import get_settings


# 加载环境变量 - 使用脚本所在目录的父目录（项目根目录）
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

# MathJax: render $...$ / $$...$$ formulas in chat bubbles (Route A).
# NOTE: This loads MathJax from CDN; demo requires network.
MATHJAX_HEAD = """
<script>
  window.MathJax = {
    tex: {
      inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
      displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
      processEscapes: true
    },
    options: {
      skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
    }
  };
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
<script>
  (function () {
    function typeset() {
      if (window.MathJax && window.MathJax.typesetPromise) {
        window.MathJax.typesetPromise().catch(function(){});
      }
    }
    function setup() {
      try {
        const obs = new MutationObserver(function () {
          // Debounce a little to avoid excessive typesets during streaming.
          clearTimeout(window.__mjx_to);
          window.__mjx_to = setTimeout(typeset, 120);
        });
        obs.observe(document.body, { childList: true, subtree: true });
      } catch (e) {}
      typeset();
    }
    window.addEventListener('load', setup);
  })();
</script>
"""

# API 基础 URL - 从环境变量读取，默认为本地
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/v1")
_settings = get_settings()
DEMO_GRADE_TIMEOUT_SECONDS = float(
    os.getenv(
        "DEMO_GRADE_TIMEOUT_SECONDS", str(_settings.grade_completion_sla_seconds + 60)
    )
)
DEMO_USER_ID = (
    os.getenv("DEMO_USER_ID") or os.getenv("DEV_USER_ID") or "dev_user"
).strip() or "dev_user"
DEMO_AUTH_TOKEN = (os.getenv("DEMO_AUTH_TOKEN") or "").strip()
DEMO_HEADERS = {"X-User-Id": DEMO_USER_ID}
if DEMO_AUTH_TOKEN:
    DEMO_HEADERS["Authorization"] = f"Bearer {DEMO_AUTH_TOKEN}"

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _build_demo_headers(*, auth_token: Optional[str]) -> Dict[str, str]:
    """
    Build request headers for backend calls.
    - If auth_token is present, use Authorization Bearer (Phase B demo login).
    - Otherwise fall back to X-User-Id (dev mode).
    """
    headers: Dict[str, str] = {"X-User-Id": DEMO_USER_ID}
    token = (auth_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _supabase_auth_endpoint(path: str) -> str:
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    return f"{url}{path}"


def _supabase_anon_key() -> str:
    return (os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY") or "").strip()


def supabase_sign_in_with_password(email: str, password: str) -> Tuple[str, str]:
    """Return (access_token, user_id)."""
    key = _supabase_anon_key()
    if not key:
        raise ValueError("SUPABASE_KEY 未配置（需要 anon key）")
    url = _supabase_auth_endpoint("/auth/v1/token?grant_type=password")
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        r = client.post(
            url,
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            json={"email": email, "password": password},
        )
    if r.status_code != 200:
        raise Exception(f"登录失败: {r.status_code} - {r.text}")
    data = r.json() if r.content else {}
    token = (data.get("access_token") or "").strip() if isinstance(data, dict) else ""
    user = data.get("user") if isinstance(data, dict) else None
    uid = (user.get("id") or "").strip() if isinstance(user, dict) else ""
    if not token or not uid:
        raise Exception("登录响应缺少 access_token/user.id")
    return token, uid


def supabase_sign_up(email: str, password: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Return (access_token?, user_id?).
    Some projects require email confirmation and won't return a token immediately.
    """
    key = _supabase_anon_key()
    if not key:
        raise ValueError("SUPABASE_KEY 未配置（需要 anon key）")
    url = _supabase_auth_endpoint("/auth/v1/signup")
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        r = client.post(
            url,
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            json={"email": email, "password": password},
        )
    if r.status_code not in (200, 201):
        raise Exception(f"注册失败: {r.status_code} - {r.text}")
    data = r.json() if r.content else {}
    token = (data.get("access_token") or "").strip() if isinstance(data, dict) else ""
    user = data.get("user") if isinstance(data, dict) else None
    uid = (user.get("id") or "").strip() if isinstance(user, dict) else ""
    return (token or None), (uid or None)


def _render_stage_lines(stage: str, elapsed_s: int) -> str:
    """
    Render a simple, UX-friendly pipeline status for demo.
    This is the reference UX for the future APP frontend.
    """
    stage = (stage or "").strip().lower()
    idx = elapsed_s % len(_SPINNER_FRAMES)
    spin = _SPINNER_FRAMES[idx]

    def done_line(text: str) -> str:
        return f"✅ {text}"

    def doing_line(text: str) -> str:
        return f"{spin} {text}（{elapsed_s}s）"

    def todo_line(text: str) -> str:
        return f"⬜ {text}"

    # Default pipeline
    upload = (
        done_line("图片上传完成")
        if stage not in {"uploading"}
        else doing_line("图片上传中…")
    )
    vision = todo_line("Vision 识别中…")
    grade = todo_line("智能批改中…")
    done = todo_line("完成")

    if stage in {"accepted", "grade_start"}:
        vision = doing_line("Vision 识别中…")
    elif stage in {"vision_start", "vision_fallback_start"}:
        vision = doing_line("Vision 识别中…")
    elif stage in {"vision_done"}:
        vision = done_line("Vision 识别完成")
        grade = doing_line("智能批改中…")
    elif stage in {"llm_start", "llm_fallback_start"}:
        vision = done_line("Vision 识别完成")
        grade = doing_line("智能批改中…")
    elif stage in {"llm_done"}:
        vision = done_line("Vision 识别完成")
        grade = done_line("智能批改完成")
        done = doing_line("整理结果…")
    elif stage in {"done"}:
        vision = done_line("Vision 识别完成")
        grade = done_line("智能批改完成")
        done = done_line("完成")
    elif stage in {"failed"}:
        vision = done_line("Vision 识别（已尝试）")
        grade = done_line("智能批改（已尝试）")
        done = f"❌ 失败（{elapsed_s}s）"

    return "\n".join(
        [
            upload,
            vision,
            grade,
            done,
        ]
    )


def _render_process_summary(lines: List[str]) -> str:
    if not lines:
        return "[过程] 正在分析题目结构…"
    return "\n".join([f"[过程] {line}" for line in lines if line])


def _update_process_summary(
    stage: str, elapsed_s: int, lines: List[str], message: Optional[str] = None
) -> List[str]:
    stage = (stage or "").strip().lower()
    msg = (message or "").strip()

    def ensure(line: str) -> None:
        if line not in lines:
            lines.append(line)

    # Always start with a visible planning line
    ensure("正在分析题目结构…")

    if msg:
        # Map known progress messages to user-friendly steps.
        if "规划" in msg or "自主阅卷" in msg or "准备" in msg:
            ensure("正在分析题目结构…")
        if "切片" in msg or "工具" in msg or "Vision" in msg or "识别" in msg:
            ensure("正在调用切片工具…")
        if "批改" in msg or "核验" in msg:
            ensure("正在核验计算…")
        if "批改结果已生成" in msg or "完成" in msg:
            ensure("已完成汇总")
        # Also keep the latest backend message for transparency (deduped).
        ensure(msg)
    else:
        if stage in {"vision_start"}:
            ensure("正在调用切片工具…")
            if elapsed_s >= 8:
                ensure("正在核验计算…")
        elif stage in {"done"}:
            ensure("正在核验计算…")
            ensure("已完成汇总")
        elif stage in {"failed"}:
            ensure("流程异常，尝试输出结果…")

    return lines


def upload_to_backend(
    file_path: str | List[str], *, session_id: Optional[str], auth_token: Optional[str]
) -> Dict[str, Any]:
    """上传文件到后端 /uploads，并返回 {upload_id, page_image_urls, ...}。

    支持单文件或多文件（多文件会合并为一次 submission，返回同一个 upload_id）。
    """
    paths: List[str] = []
    if isinstance(file_path, list):
        paths = [str(p) for p in file_path if str(p).strip()]
    else:
        paths = [str(file_path)]

    if not paths:
        raise ValueError("文件不存在")
    for p in paths:
        if not p or not os.path.exists(p):
            raise ValueError(f"文件不存在: {p}")
        # 检查文件大小 (<20MB each)
        file_size = os.path.getsize(p)
        if file_size > 20 * 1024 * 1024:
            raise ValueError(f"文件超过 20MB: {p}")
    params: Dict[str, str] = {}
    if session_id:
        params["session_id"] = str(session_id)

    with ExitStack() as stack:
        # Backend accepts repeated "file" fields (List[UploadFile]).
        files: List[Tuple[str, Tuple[str, Any, str]]] = []
        for p in paths:
            filename = os.path.basename(p)
            content_type = (
                mimetypes.guess_type(p)[0] or "application/octet-stream"
            )
            f = stack.enter_context(open(p, "rb"))
            files.append(("file", (filename, f, content_type)))
        with httpx.Client(timeout=120.0) as client:
            r = client.post(
                f"{API_BASE_URL}/uploads",
                files=files,
                params=params,
                headers=_build_demo_headers(auth_token=auth_token),
            )
    if r.status_code != 200:
        raise Exception(f"上传失败: {r.status_code} - {r.text}")
    data = r.json()
    if not isinstance(data, dict) or not data.get("upload_id"):
        raise Exception(f"上传失败：响应异常 {data}")
    return data


def format_grading_result(result: Dict[str, Any]) -> str:
    """格式化批改结果为 Markdown"""
    md = "## 📊 评分结果\n\n"
    md += f"- **科目 (Subject)**: {result.get('subject', 'N/A')}\n"
    md += f"- **状态 (Status)**: {result.get('status', 'N/A')}\n"
    md += f"- **Session ID**: `{result.get('session_id', 'N/A')}`\n"
    md += f"- **摘要 (Summary)**: {result.get('summary', 'N/A')}\n"
    wrong_count = result.get("wrong_count")
    wrong_items = result.get("wrong_items") or []
    if wrong_count is None and isinstance(wrong_items, list):
        wrong_count = len(wrong_items)
    md += f"- **错题数 (Wrong Count)**: {wrong_count if wrong_count is not None else 'N/A'}\n"
    md += "\n"

    status = result.get("status")
    if status and status != "done":
        md += "### ❌ 批改失败\n"
        if result.get("warnings"):
            md += "原因（warnings）：\n"
            for w in result.get("warnings") or []:
                md += f"- {w}\n"
        md += "\n"
        # 仍然继续展示 vision_raw_text 以便核对

    if wrong_items:
        md += "### ❌ 错题列表\n"
        for item in wrong_items:
            qnum = item.get("question_number") or item.get("question_index") or "N/A"
            qtext = item.get("question_content") or item.get("question") or "N/A"
            md += f"**题 {qnum}** {qtext}\n"
            md += f"- 错误原因: {item.get('reason', 'N/A')}\n"
            if item.get("analysis"):
                md += f"- 分析: {item.get('analysis')}\n"
            bbox = item.get("bbox")
            if bbox:
                md += f"- 位置 (BBox): `{bbox}`\n"
            md += "\n"
    else:
        if status == "done":
            md += "### ✅ 全对 (All Correct!)\n太棒了！没有发现错误。\n"
        else:
            md += "### ⚠️ 未生成错题列表\n批改未完成（LLM 超时/解析失败等），因此无法给出错题判定。\n"

    if result.get("warnings"):
        md += "\n### ⚠️ 警告\n"
        for warning in result["warnings"]:
            md += f"- {warning}\n"

    # 运行链路（可解释性）：展示后端记录的 qbank 元信息（如果可用）
    qb = result.get("_qbank_meta")
    if isinstance(qb, dict):
        meta = qb.get("meta") if isinstance(qb.get("meta"), dict) else {}
        md += "\n### 🔎 本次批改链路（后端记录）\n"
        md += f"- qbank 题数: {qb.get('questions_count', 'N/A')}（含选项: {qb.get('questions_with_options', 'N/A')}）\n"
        md += f"- vision_raw_len: {qb.get('vision_raw_len', 'N/A')}\n"
        if meta:
            md += f"- Vision provider: {meta.get('vision_provider_used', meta.get('vision_provider_requested', 'N/A'))}\n"
            if meta.get("vision_used_base64_fallback") is not None:
                md += (
                    f"- Vision base64 兜底: {meta.get('vision_used_base64_fallback')}\n"
                )
            md += f"- LLM provider: {meta.get('llm_provider_used', meta.get('llm_provider_requested', 'N/A'))}\n"
            if meta.get("llm_used_fallback") is not None:
                md += f"- LLM fallback: {meta.get('llm_used_fallback')}\n"
            t = meta.get("timings_ms") or {}
            if isinstance(t, dict) and t:
                md += f"- 耗时(ms): vision={t.get('vision_ms','?')} llm={t.get('llm_ms','?')}\n"

    return md


def format_vision_raw_text(result: Dict[str, Any]) -> str:
    vision_raw = result.get("vision_raw_text")
    if not vision_raw:
        return "> 未返回识别原文（可能识别失败或超时）。"
    vision_raw = _repair_latex_escapes(vision_raw)
    # Strip various format markers
    if "【图形视觉事实】" in vision_raw:
        vision_raw = vision_raw.split("【图形视觉事实】", 1)[0].strip()
    vision_raw = re.sub(r"^【OCR识别原文】\s*", "", vision_raw).strip()
    # Strip ---OCR_TEXT--- markers and VISUAL_FACTS markers
    vision_raw = re.sub(
        r"---OCR[识识]?别?原文---\s*", "", vision_raw, flags=re.IGNORECASE
    ).strip()
    vision_raw = re.sub(
        r"---END_OCR_TEXT---\s*", "", vision_raw, flags=re.IGNORECASE
    ).strip()
    vision_raw = re.sub(
        r"---VISUAL_FACTS_JSON---.*", "", vision_raw, flags=re.DOTALL
    ).strip()
    vision_raw = re.sub(r"<<<[A-Z_]+>>>\s*", "", vision_raw).strip()
    vision_raw = re.sub(r"<<<END_[A-Z_]+>>>\s*", "", vision_raw).strip()

    # Strip JSON blocks that might appear at the end (e.g., visual_facts JSON)
    vision_raw = re.sub(r"```json\s*\{.*", "", vision_raw, flags=re.DOTALL).strip()
    vision_raw = re.sub(
        r"\{[\s\n]*\"questions\":\s*\{.*", "", vision_raw, flags=re.DOTALL
    ).strip()

    # Convert LaTeX delimiters from \( \) to $ $ for MathJax rendering
    # First handle escaped backslashes: \\( \\) -> $ $
    vision_raw = re.sub(r"\\\(", "$", vision_raw)
    vision_raw = re.sub(r"\\\)", "$", vision_raw)
    # Also handle display math: \[ \] -> $$ $$
    vision_raw = re.sub(r"\\\[", "$$", vision_raw)
    vision_raw = re.sub(r"\\\]", "$$", vision_raw)

    # Improve readability: if OCR text is flattened into a single line, insert best-effort separators.
    try:
        raw = str(vision_raw or "")
        if raw.count("\n") < 3:
            raw = re.sub(r"\s*(###\s*Page\s*\d+)", r"\n\n\1", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*(###\s*第)", r"\n\n\1", raw)
            raw = re.sub(r"(第\s*\d{1,3}\s*题)", r"\n\n\1", raw)
            raw = re.sub(
                r"(?<!\d)(\d{1,3})[\.．]\s*(?=[^0-9])",
                r"\n\n\1. ",
                raw,
            )
            raw = re.sub(
                r"\s*(题目|学生答案|学生作答状态|作答状态|答案|选项|解析|解答)\s*[:：]\s*",
                r"\n\1：",
                raw,
            )
            raw = re.sub(r"\n{3,}", "\n\n", raw)
            vision_raw = raw.strip()
    except Exception:
        pass

    # Use blockquote format to allow LaTeX rendering via MathJax (instead of code block which prevents it)
    # Add blockquote prefix to each line
    lines = vision_raw.split("\n")
    quoted_lines = [f"> {line}" for line in lines]
    quoted_text = "\n".join(quoted_lines)
    return (
        "<details>\n"
        "<summary>📷 识别原文（点击查看）</summary>\n\n"
        f"{quoted_text}\n"
        "</details>"
    )


def _normalize_bool_str(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    s = str(value or "").strip().lower()
    return s if s in {"true", "false", "unknown"} else "unknown"


def _repair_latex_escapes(text: Any) -> str:
    """
    Recover common LaTeX commands that were broken by JSON escape parsing.
    Example: "\\frac" -> "\f" (form feed) + "rac" after json.loads.
    """
    if text is None:
        return ""
    s = str(text)
    # JSON escape side effects: \f, \t, \b, \v, \r become control chars.
    # Convert them back to backslash-prefixed sequences.
    s = s.replace("\f", "\\f")
    s = s.replace("\t", "\\t")
    s = s.replace("\b", "\\b")
    s = s.replace("\v", "\\v")
    s = s.replace("\r", "\\r")
    return s


def _translate_relative(text: str) -> str:
    if not text:
        return ""
    s = str(text).strip()
    # Remove common prefixes like "line ", "point "
    s = re.sub(r"\bline\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bpoint\s+", "", s, flags=re.IGNORECASE)
    parts = re.split(r"[;，,]", s)
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        m = re.match(r"left_of\s*(.+)", p, flags=re.IGNORECASE)
        if m:
            out.append(f"在 {m.group(1).strip()} 左侧")
            continue
        m = re.match(r"right_of\s*(.+)", p, flags=re.IGNORECASE)
        if m:
            out.append(f"在 {m.group(1).strip()} 右侧")
            continue
        m = re.match(r"above\s*(.+)", p, flags=re.IGNORECASE)
        if m:
            out.append(f"在 {m.group(1).strip()} 上方")
            continue
        m = re.match(r"below\s*(.+)", p, flags=re.IGNORECASE)
        if m:
            out.append(f"在 {m.group(1).strip()} 下方")
            continue
        m = re.match(r"connects\s*(.+)", p, flags=re.IGNORECASE)
        if m:
            out.append(f"连接 {m.group(1).strip()}")
            continue
        m = re.match(r"on\s+(.+)", p, flags=re.IGNORECASE)
        if m:
            out.append(f"在 {m.group(1).strip()} 上")
            continue
        # Pattern: "X is above Y" -> "X 在 Y 上方"
        m = re.match(r"(.+?)\s+is\s+above\s+(.+)", p, flags=re.IGNORECASE)
        if m:
            out.append(f"{m.group(1).strip()} 在 {m.group(2).strip()} 上方")
            continue
        m = re.match(r"(.+?)\s+is\s+below\s+(.+)", p, flags=re.IGNORECASE)
        if m:
            out.append(f"{m.group(1).strip()} 在 {m.group(2).strip()} 下方")
            continue
        m = re.match(r"(.+?)\s+is\s+left\s+of\s+(.+)", p, flags=re.IGNORECASE)
        if m:
            out.append(f"{m.group(1).strip()} 在 {m.group(2).strip()} 左侧")
            continue
        m = re.match(r"(.+?)\s+is\s+right\s+of\s+(.+)", p, flags=re.IGNORECASE)
        if m:
            out.append(f"{m.group(1).strip()} 在 {m.group(2).strip()} 右侧")
            continue
        m = re.match(r"(.+?)\s+is\s+(?:vertical|horizontal)", p, flags=re.IGNORECASE)
        if m:
            # Keep as-is but translate keywords
            translated = p.replace("is vertical", "是竖直的").replace(
                "is horizontal", "是水平的"
            )
            out.append(translated)
            continue
        out.append(p)
    return "；".join(out)


def _direction_zh(direction: str) -> str:
    d = (direction or "").strip().lower()
    return {
        "horizontal": "水平",
        "vertical": "竖直",
        "slanted": "倾斜",
    }.get(d, "方向未知")


def _format_visual_facts_nl(vf: Dict[str, Any]) -> List[str]:
    if not isinstance(vf, dict):
        return []
    facts = vf.get("facts") if isinstance(vf.get("facts"), dict) else {}
    lines: List[str] = []
    for it in facts.get("lines") or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        direction = _direction_zh(str(it.get("direction") or ""))
        rel = _translate_relative(str(it.get("relative") or ""))
        if rel:
            lines.append(f"{name} 为{direction}线段，{rel}")
        else:
            lines.append(f"{name} 为{direction}线段")
    for it in facts.get("points") or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        rel = _translate_relative(str(it.get("relative") or ""))
        if name and rel:
            lines.append(f"{name} {rel}")
    for it in facts.get("angles") or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        segs = [name]
        at = str(it.get("at") or "").strip()
        if at:
            segs.append(f"在 {at} 点")
        between = it.get("between") or []
        if isinstance(between, list) and between:
            segs.append(
                "夹在 " + " 与 ".join([str(x) for x in between if str(x).strip()])
            )
        side = str(it.get("transversal_side") or "").strip().lower()
        if side in {"left", "right"}:
            segs.append(f"在截线{('左' if side == 'left' else '右')}侧")
        between_lines = str(it.get("between_lines") or "").strip().lower()
        if between_lines == "true":
            segs.append("在被截线之间")
        elif between_lines == "false":
            segs.append("在被截线外侧")
        lines.append("，".join(segs))
    for it in facts.get("labels") or []:
        s = str(it).strip()
        if s:
            # Translate common patterns like "30° at point C" -> "30° 在 C 点"
            s = re.sub(r"\bat\s+(point\s+)?", "在 ", s, flags=re.IGNORECASE)
            s = s.replace("point ", "")
            lines.append(s)
    for it in facts.get("spatial") or []:
        s = str(it).strip()
        if s:
            # Translate spatial relations
            s = _translate_relative(s) or s
            lines.append(s)
    # Unknowns: show what AI couldn't determine
    unknowns = vf.get("unknowns") or []
    if unknowns and isinstance(unknowns, list):
        unknown_strs = [str(u).strip() for u in unknowns if str(u).strip()]
        if unknown_strs:
            lines.append(f"不确定：{'、'.join(unknown_strs)}")
    # Hypotheses: show AI inferences with confidence
    hypotheses = vf.get("hypotheses") or []
    for h in hypotheses:
        if not isinstance(h, dict):
            continue
        stmt = str(h.get("statement") or "").strip()
        conf = h.get("confidence")
        if stmt:
            if conf is not None:
                lines.append(f"AI 推断：{stmt}（置信度 {conf}）")
            else:
                lines.append(f"AI 推断：{stmt}")
    return lines


def _order_qnums(keys: List[str]) -> List[str]:
    """Sort question numbers: 1, 2, 3, 5, 5(1), 5(2), 6, 6(1), 6(2), ..., 思维与拓展"""
    import re

    def sort_key(k: str):
        m = re.match(r"^(\d+)(?:\((\d+)\))?", str(k))
        if m:
            base = int(m.group(1))
            sub = int(m.group(2)) if m.group(2) else 0
            return (0, base, sub, k)
        return (1, 0, 0, k)

    try:
        return sorted(keys, key=sort_key)
    except Exception:
        return keys


def build_grade_report_sections(result: Dict[str, Any]) -> List[str]:
    """Build modular report sections for streaming display."""
    sections: List[str] = []

    status = result.get("status")
    wrong_items = result.get("wrong_items") or []
    wrong_count = result.get("wrong_count")
    if wrong_count is None and isinstance(wrong_items, list):
        wrong_count = len(wrong_items)

    if status and status != "done":
        if status == "rejected":
            md = "❌ 输入非作业图片，已拒绝批改\n"
        else:
            md = "❌ 批改失败\n"
        if result.get("warnings"):
            md += "原因（warnings）：\n"
            for w in result.get("warnings") or []:
                md += f"- {w}\n"
        return [md]

    vf_map = result.get("visual_facts")
    vf_map = vf_map if isinstance(vf_map, dict) else {}

    questions_list = result.get("questions") or []
    questions_map: Dict[str, Dict[str, Any]] = {}
    for q in questions_list:
        if isinstance(q, dict):
            qn = q.get("question_number") or q.get("question_index")
            if qn:
                questions_map[str(qn)] = q

    wrong_qns: List[str] = []
    for item in wrong_items:
        qnum = (
            item.get("question_number") or item.get("question_index") or item.get("id")
        )
        if qnum is not None:
            wrong_qns.append(str(qnum))
    wrong_qn_set = {str(q) for q in wrong_qns}

    all_qns_set = set(questions_map.keys()) | set(vf_map.keys())
    all_qns = _order_qnums(list(all_qns_set))

    internal_qn_patterns = ["thinking_and_expansion", "extra", "bonus"]
    import re

    has_subquestions = set()
    for q in all_qns:
        m = re.match(r"^(\d+)\(\d+\)", str(q))
        if m:
            has_subquestions.add(m.group(1))

    incorrect_qns: List[str] = []
    uncertain_qns: List[str] = []
    correct_qns: List[str] = []
    if questions_map:
        for qn, q_data in questions_map.items():
            verdict = str(q_data.get("verdict") or "").strip().lower()
            if verdict == "incorrect":
                incorrect_qns.append(str(qn))
            elif verdict == "uncertain":
                uncertain_qns.append(str(qn))
            elif verdict == "correct":
                correct_qns.append(str(qn))
        incorrect_qns = _order_qnums(list(set(incorrect_qns)))
        uncertain_qns = _order_qnums(list(set(uncertain_qns)))
        correct_qns = _order_qnums(list(set(correct_qns)))
    else:
        correct_qns = [
            q
            for q in all_qns
            if q not in wrong_qn_set
            and q.lower() not in internal_qn_patterns
            and not (q.replace("_", "").isalpha() and len(q) > 10)
            and not (str(q).isdigit() and str(q) in has_subquestions)
        ]

    header = "✅ 批改完成，以下是识别与批改结果：\n\n"
    header += "⚠️ 批改依据说明\n"
    header += "以下结果基于 AI 对图片的识别和图形分析，可能存在误读或漏判。\n"
    header += "建议核对下方“识别原文”和“AI 识别依据”后再参考批改结论。\n\n"
    header += "📊 批改结果\n"

    uncertain_total = len(uncertain_qns)
    if questions_map:
        correct_count = len(correct_qns)
        wrong_total = (
            len(incorrect_qns) if incorrect_qns else (wrong_count or len(wrong_items))
        )
    elif result.get("total_items") is not None and wrong_count is not None:
        correct_count = max(
            0, int(result.get("total_items") or 0) - int(wrong_count or 0)
        )
        wrong_total = int(wrong_count or 0)
    else:
        correct_count = None
        wrong_total = wrong_count if wrong_count is not None else len(wrong_items)

    if correct_count is None:
        header += f"✅ 正确：待确认 | ❌ 错误：{wrong_total} 道 | ⚠️ 待确认：{uncertain_total} 道\n"
    else:
        header += f"✅ 正确：{correct_count} 道 | ❌ 错误：{wrong_total} 道 | ⚠️ 待确认：{uncertain_total} 道\n"
    sections.append(header)

    # Wrong items (incorrect)
    incorrect_items: List[Dict[str, Any]] = []
    if wrong_items:
        incorrect_items = list(wrong_items)
    elif questions_map:
        for qn in incorrect_qns:
            q_data = questions_map.get(str(qn)) or {}
            incorrect_items.append(
                {
                    "question_number": qn,
                    "question_content": q_data.get("question_content")
                    or q_data.get("question"),
                    "reason": q_data.get("reason") or "判定为错误",
                    "judgment_basis": q_data.get("judgment_basis") or [],
                }
            )

    if incorrect_items:
        md = "---\n"
        for item in incorrect_items:
            qnum = item.get("question_number") or item.get("question_index") or "N/A"
            qtext = _repair_latex_escapes(
                item.get("question_content") or item.get("question") or "N/A"
            )
            reason = _repair_latex_escapes(item.get("reason", "N/A"))
            md += f"❌ 题 {qnum}（展开） {qtext}\n"
            md += f"  - 错误原因：{reason}\n"

            basis = item.get("judgment_basis") or []
            if not basis:
                q_data = questions_map.get(str(qnum)) or {}
                basis = q_data.get("judgment_basis") or []
            if basis and isinstance(basis, list):
                md += "  - AI 识别依据：\n"
                for b in basis:
                    if isinstance(b, str) and b.strip():
                        md += f"    - {_repair_latex_escapes(b.strip())}\n"
            else:
                md += "  - AI 识别依据：未返回\n"
            md += "\n"
        sections.append(md)

    # Uncertain items (待确认)
    if uncertain_qns:
        md = "---\n"
        for qn in uncertain_qns:
            q_data = questions_map.get(str(qn)) or {}
            qtext = _repair_latex_escapes(
                q_data.get("question_content") or q_data.get("question") or "N/A"
            )
            reason = _repair_latex_escapes(q_data.get("reason") or "暂无法确认")
            md += f"⚠️ 题 {qn}（展开） {qtext}\n"
            md += f"  - 无法确认原因：{reason}\n"
            basis = q_data.get("judgment_basis") or []
            if basis and isinstance(basis, list):
                md += "  - AI 识别依据：\n"
                for b in basis:
                    if isinstance(b, str) and b.strip():
                        md += f"    - {_repair_latex_escapes(b.strip())}\n"
            else:
                md += "  - AI 识别依据：未返回\n"
            md += "\n"
        sections.append(md)

    # Correct items (only list numbers)
    if correct_qns:
        md = "---\n"
        md += "✅ 正确题目：" + "，".join([str(q) for q in correct_qns]) + "\n\n"
        sections.append(md)

    if result.get("warnings"):
        md = "⚠️ 警告\n"
        seen = set()
        for warning in result.get("warnings") or []:
            if warning in seen:
                continue
            if (
                "URL 拉取失败" in warning
                or "url_head status" in warning
                or "视觉事实" in warning
            ):
                seen.add(warning)
                continue
            if str(warning).strip().lower() in {"preprocess_disabled"}:
                seen.add(warning)
                continue
            md += f"- {warning}\n"
            seen.add(warning)
        md += "\n"
        if md.strip() != "⚠️ 警告":
            sections.append(md)

    sections.append("---\n" + format_vision_raw_text(result))
    return sections


def format_grade_report(result: Dict[str, Any]) -> str:
    """Render grading output for non-streaming consumers."""
    return "\n\n".join(build_grade_report_sections(result))


def _chunk_text_for_stream(text: str, *, max_chars: int = 240) -> List[str]:
    """Split text into small chunks for streaming display."""
    if not text:
        return [""]
    chunks: List[str] = []
    buf = ""
    for line in text.splitlines(keepends=True):
        if buf and len(buf) + len(line) > max_chars:
            chunks.append(buf)
            buf = line
        else:
            buf += line
    if buf:
        chunks.append(buf)
    return chunks


async def call_grade_api(
    *,
    upload_id: str,
    subject: str,
    provider: str,
    llm_provider: str,
    session_id: str,
    auth_token: Optional[str],
    force_async: bool = False,
) -> Dict[str, Any]:
    """调用后端 /api/v1/grade（推荐：upload_id -> 后端反查 images）。"""
    payload = {
        "images": [],
        "upload_id": upload_id,
        "subject": subject,
        "session_id": session_id,
        "vision_provider": provider,
        "llm_provider": llm_provider,
    }

    # Demo 端的 HTTP timeout 必须 ≥ 后端 grade 的 SLA，否则前端会“系统报错”但后端仍在跑。
    async with httpx.AsyncClient(timeout=DEMO_GRADE_TIMEOUT_SECONDS) as client:
        headers = _build_demo_headers(auth_token=auth_token)
        if force_async:
            headers["X-Force-Async"] = "1"
        response = await client.post(
            f"{API_BASE_URL}/grade",
            json=payload,
            headers=headers,
        )

    if response.status_code not in (200, 202):
        raise Exception(f"API 调用失败: {response.status_code} - {response.text}")

    return response.json()


async def call_grade_progress(
    session_id: str, *, auth_token: Optional[str]
) -> Optional[Dict[str, Any]]:
    """轮询后端 /session/{session_id}/progress，获取实时阶段信息（best-effort）。"""
    if not session_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{API_BASE_URL}/session/{session_id}/progress",
                headers=_build_demo_headers(auth_token=auth_token),
            )
        if r.status_code != 200:
            return None
        data = r.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def call_qbank_meta(
    session_id: str, *, auth_token: Optional[str]
) -> Optional[Dict[str, Any]]:
    """读取后端 qbank 元信息，用于解释本次批改链路（vision/llm 走了哪条路、耗时等）。"""
    if not session_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{API_BASE_URL}/session/{session_id}/qbank",
                headers=_build_demo_headers(auth_token=auth_token),
            )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


async def call_chat_api(
    question: str,
    session_id: str,
    subject: str,
    context_item_ids: Optional[List[str]] = None,
    llm_model: Optional[str] = None,
    auth_token: Optional[str] = None,
) -> str:
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
        "context_item_ids": context_item_ids or [],
        "llm_model": llm_model,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{API_BASE_URL}/chat",
            json=payload,
            headers=_build_demo_headers(auth_token=auth_token),
        )

    if response.status_code != 200:
        raise Exception(f"API 调用失败: {response.status_code} - {response.text}")

    # 解析 SSE 响应 - 遍历事件，取最后一条 assistant 消息
    content = ""
    current_event = ""
    for line in response.text.split("\n"):
        line = line.strip()
        if line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:"):
            data = line[5:].strip()
            if data and data != '{"status":"done"}':
                try:
                    import json

                    json_data = json.loads(data)
                    if current_event == "chat" and "messages" in json_data:
                        messages = json_data.get("messages", [])
                        # 反向查找最后一条助手消息
                        for msg in reversed(messages):
                            if msg.get("role") == "assistant":
                                content = msg.get("content", "")
                                break
                except Exception as e:
                    print(f"SSE parse error: {e}, data: {data}")
                    pass

    return content or "无响应"


# ========== Demo UI 2.0: Workflow Console Logic ==========


async def _call_job_status(job_id: str, *, auth_token: Optional[str]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{API_BASE_URL}/jobs/{job_id}",
            headers=_build_demo_headers(auth_token=auth_token),
        )
    if r.status_code != 200:
        raise Exception(f"job 查询失败: {r.status_code} - {r.text}")
    data = r.json() if r.content else {}
    return data if isinstance(data, dict) else {}


async def _call_create_report_job(
    *,
    window_days: int = 7,
    subject: Optional[str],
    submission_id: Optional[str] = None,
    auth_token: Optional[str],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"window_days": int(window_days)}
    if subject:
        payload["subject"] = str(subject).strip()
    sid = str(submission_id or "").strip()
    if sid:
        payload["submission_id"] = sid
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{API_BASE_URL}/reports",
            json=payload,
            headers=_build_demo_headers(auth_token=auth_token),
        )
    if r.status_code not in (200, 202):
        raise Exception(f"report job 创建失败: {r.status_code} - {r.text}")
    data = r.json() if r.content else {}
    return data if isinstance(data, dict) else {}


def _fmt_ms(ms: Optional[int]) -> str:
    if ms is None:
        return "n/a"
    try:
        v = int(ms)
    except Exception:
        return "n/a"
    if v < 0:
        v = 0
    if v >= 60_000:
        return f"{v / 1000.0:.1f}s"
    if v >= 1000:
        return f"{v / 1000.0:.2f}s"
    return f"{v}ms"


def _now_m() -> float:
    return time.monotonic()


def _ms_between(t1: Optional[float], t2: Optional[float]) -> Optional[int]:
    if t1 is None or t2 is None:
        return None
    try:
        return int(max(0.0, (float(t2) - float(t1)) * 1000.0))
    except Exception:
        return None


def _render_timing_panel_md(
    *,
    upload_id: str,
    session_id: str,
    timing_ctx: Dict[str, Any],
    grade_job: Optional[Dict[str, Any]] = None,
    report_job: Optional[Dict[str, Any]] = None,
) -> str:
    ctx = timing_ctx or {}
    lines: List[str] = []
    lines.append("### ⏱️ 时延拆解（本次提交）")
    if upload_id:
        lines.append(f"- submission_id: `{upload_id}`")
    if session_id:
        lines.append(f"- session_id: `{session_id}`")

    lines.append("")
    lines.append("**端到端（前端可观测）**")
    lines.append(f"- upload_ms: `{_fmt_ms(ctx.get('upload_ms'))}`")
    lines.append(f"- grade_submit_ms: `{_fmt_ms(ctx.get('grade_submit_ms'))}`")
    lines.append(f"- grade_queue_wait_ms: `{_fmt_ms(ctx.get('grade_queue_wait_ms'))}`")
    lines.append(f"- grade_worker_elapsed_ms: `{_fmt_ms(ctx.get('grade_worker_elapsed_ms'))}`")
    lines.append(f"- grade_wall_ms: `{_fmt_ms(ctx.get('grade_wall_ms'))}`")
    lines.append(f"- report_queue_wait_ms: `{_fmt_ms(ctx.get('report_queue_wait_ms'))}`")
    lines.append(f"- report_wall_ms: `{_fmt_ms(ctx.get('report_wall_ms'))}`")

    qbank = ctx.get("qbank_meta")
    meta: Dict[str, Any] = {}
    if isinstance(qbank, dict) and isinstance(qbank.get("meta"), dict):
        meta = qbank.get("meta") or {}

    timings_ms = meta.get("timings_ms") if isinstance(meta.get("timings_ms"), dict) else {}
    llm_trace = meta.get("llm_trace") if isinstance(meta.get("llm_trace"), dict) else {}

    if timings_ms:
        lines.append("")
        lines.append("**Agent 内部计时（qbank.meta.timings_ms）**")
        # Prefer a stable subset if present.
        preferred = [
            "preprocess_total_ms",
            "llm_aggregate_call_ms",
            "llm_aggregate_parse_ms",
            "grade_total_duration_ms",
        ]
        for k in preferred:
            if k in timings_ms:
                lines.append(f"- {k}: `{_fmt_ms(timings_ms.get(k))}`")
        # Add remaining keys (short list).
        others = [k for k in sorted(timings_ms.keys()) if k not in set(preferred)]
        for k in others[:12]:
            lines.append(f"- {k}: `{_fmt_ms(timings_ms.get(k))}`")
        if len(others) > 12:
            lines.append(f"- ... ({len(others) - 12} more)")

    if llm_trace:
        lines.append("")
        lines.append("**Ark 追溯（qbank.meta.llm_trace）**")
        for k in ["ark_response_id", "ark_image_process_requested", "grade_image_input_variant", "ark_image_input_mode"]:
            if k in llm_trace:
                lines.append(f"- {k}: `{llm_trace.get(k)}`")

    if isinstance(grade_job, dict) and grade_job.get("status"):
        lines.append("")
        lines.append("**Job 状态**")
        lines.append(f"- grade_job_status: `{grade_job.get('status')}`")
        if grade_job.get("elapsed_ms") is not None:
            lines.append(f"- grade_job_elapsed_ms: `{_fmt_ms(grade_job.get('elapsed_ms'))}`")
        if grade_job.get("error"):
            lines.append(f"- grade_job_error: `{str(grade_job.get('error'))[:500]}`")
    if isinstance(report_job, dict) and report_job.get("status"):
        if "Job 状态" not in "\n".join(lines):
            lines.append("")
            lines.append("**Job 状态**")
        lines.append(f"- report_job_status: `{report_job.get('status')}`")
        if report_job.get("error"):
            lines.append(f"- report_job_error: `{str(report_job.get('error'))[:500]}`")

    return "\n".join(lines).strip() + "\n"


def _render_timing_summary_md(
    *,
    upload_id: str,
    session_id: str,
    timing_ctx: Dict[str, Any],
) -> str:
    ctx = timing_ctx or {}
    upload_ms = ctx.get("upload_ms")
    grade_submit_ms = ctx.get("grade_submit_ms")
    grade_wall_ms = ctx.get("grade_wall_ms")
    report_wall_ms = ctx.get("report_wall_ms")

    e2e_grade_ms = None
    try:
        if upload_ms is not None and grade_submit_ms is not None and grade_wall_ms is not None:
            e2e_grade_ms = int(upload_ms) + int(grade_submit_ms) + int(grade_wall_ms)
    except Exception:
        e2e_grade_ms = None

    e2e_full_ms = None
    try:
        if e2e_grade_ms is not None and report_wall_ms is not None:
            e2e_full_ms = int(e2e_grade_ms) + int(report_wall_ms)
    except Exception:
        e2e_full_ms = None

    lines: List[str] = []
    lines.append("### ⏱️ 用时概览")
    if upload_id:
        lines.append(f"- submission_id: `{upload_id}`")
    if session_id:
        lines.append(f"- session_id: `{session_id}`")
    lines.append("")
    lines.append(f"- 上传：`{_fmt_ms(upload_ms)}`")
    lines.append(f"- grade（排队+执行）：`{_fmt_ms(grade_wall_ms)}`")
    lines.append(f"- 用户感知 E2E（提交→看到 grade 完成）：`{_fmt_ms(e2e_grade_ms)}`")
    if report_wall_ms is not None:
        lines.append(f"- report：`{_fmt_ms(report_wall_ms)}`")
        lines.append(f"- 用户感知 E2E（含报告）：`{_fmt_ms(e2e_full_ms)}`")
    lines.append("")
    lines.append(
        "（已隐藏详细分段；需要排查时再展开“高级：调试指标”）"
    )
    return "\n".join(lines).strip() + "\n"


async def _call_report_job(job_id: str, *, auth_token: Optional[str]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{API_BASE_URL}/reports/jobs/{job_id}",
            headers=_build_demo_headers(auth_token=auth_token),
        )
    if r.status_code != 200:
        raise Exception(f"report job 查询失败: {r.status_code} - {r.text}")
    data = r.json() if r.content else {}
    return data if isinstance(data, dict) else {}


async def _call_get_report(
    report_id: str, *, auth_token: Optional[str]
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{API_BASE_URL}/reports/{report_id}",
            headers=_build_demo_headers(auth_token=auth_token),
        )
    if r.status_code != 200:
        raise Exception(f"report 查询失败: {r.status_code} - {r.text}")
    data = r.json() if r.content else {}
    return data if isinstance(data, dict) else {}



async def submit_job_handler(img_path, auth_token):
    """Async Submit (Real): uploads -> /grade (forced async) -> returns job_id + session_id."""
    # Hardcoded defaults for simplified UI
    subject = "math"
    provider = "doubao"
    llm_provider = "ark"

    paths: List[str] = []
    if isinstance(img_path, list):
        for it in img_path:
            if hasattr(it, "name"):
                paths.append(str(it.name))
            else:
                paths.append(str(it))
    else:
        if hasattr(img_path, "name"):
            paths = [str(img_path.name)]
        else:
            paths = [str(img_path)]

    paths = [p for p in paths if p and str(p).strip()]
    if not paths:
        raise gr.Error("请先上传图片")

    auth_token = (auth_token or "").strip() or None
    session_id = f"demo_{uuid.uuid4().hex[:8]}"
    timing_ctx: Dict[str, Any] = {
        "upload_started_m": float(_now_m()),
    }

    # 1. Upload (Real)
    try:
        # Reuse existing upload logic
        t0 = _now_m()
        upload_resp = await asyncio.to_thread(
            upload_to_backend,
            paths if len(paths) > 1 else paths[0],
            session_id=session_id,
            auth_token=auth_token,
        )
        timing_ctx["upload_ms"] = _ms_between(t0, _now_m())
        upload_id = upload_resp.get("upload_id")
        page_image_urls = upload_resp.get("page_image_urls")
        if not isinstance(page_image_urls, list):
            page_image_urls = []
        page_image_urls = [str(u) for u in page_image_urls if str(u).strip()]
        timing_ctx["uploaded_pages"] = int(len(page_image_urls))
    except Exception as e:
        raise gr.Error(f"Upload failed: {e}")

    if not upload_id:
        raise gr.Error("Upload failed: missing upload_id")

    # 2. /grade (Force Async) -> get job_id + session_id
    try:
        t1 = _now_m()
        grade_resp = await call_grade_api(
            upload_id=str(upload_id),
            subject=str(subject),
            provider=str(provider),
            llm_provider=str(llm_provider),
            session_id=str(session_id),
            auth_token=auth_token,
            force_async=True,
        )
        timing_ctx["grade_submit_ms"] = _ms_between(t1, _now_m())
    except Exception as e:
        raise gr.Error(f"/grade failed: {e}")

    job_id = str((grade_resp or {}).get("job_id") or "").strip()
    session_id_out = str((grade_resp or {}).get("session_id") or session_id).strip()
    if not job_id:
        raise gr.Error("grade 响应缺少 job_id（预期 202 异步返回）")

    timing_ctx["grade_job_submitted_m"] = float(_now_m())

    uploaded_pages_n = int(timing_ctx.get("uploaded_pages") or 0)
    selected_files_n = int(len(paths))
    if uploaded_pages_n and uploaded_pages_n != selected_files_n:
        timing_ctx["upload_page_mismatch"] = {
            "selected_files": selected_files_n,
            "uploaded_pages": uploaded_pages_n,
        }

    return (
        job_id,
        session_id_out,
        str(upload_id),
        "",  # report_job_id_state (reset)
        "",  # report_id_state (reset)
        gr.update(visible=True),  # Show Monitor Panel
        (
            "✅ 作业已提交 (Async)\n\n"
            f"- files(selected): `{len(paths)}`\n"
            f"- pages(uploaded): `{uploaded_pages_n or 'unknown'}`\n"
            f"- upload_id: `{upload_id}`\n"
            f"- session_id: `{session_id_out}`\n"
            f"- job_id: `{job_id}`\n"
            + (
                "\n⚠️ 注意：你选择了多张文件，但后端只生成了更少的 `page_image_urls`。"
                "这通常意味着某些文件格式未被识别/转码（常见：HEIC/HEIF）。"
                "建议先转成 JPG/PNG 或检查后端是否安装了 HEIC 解码依赖。"
                if (uploaded_pages_n and uploaded_pages_n != len(paths))
                else ""
            )
        ),
        gr.update(
            value="已提交任务，等待 grade_worker ...", visible=True
        ),
        "",  # timings_summary_md (reset)
        "",  # timings_detail_md (reset)
        "",  # grade_result_md (reset)
        "",  # class_report_md (reset)
        gr.update(interactive=False, value="生成学业报告"),
        timing_ctx,
        {
            "total_pages": int(uploaded_pages_n or len(paths)),
            "done_pages": 0,
            "page_context": {},
        },
        [],
    )


async def generate_report_handler(upload_id: str, auth_token: str, timing_ctx: Dict[str, Any]):
    """Manually trigger single-submission report generation."""
    submission_id = str(upload_id or "").strip()
    if not submission_id:
        raise gr.Error("缺少 submission_id（请先提交作业并等待 grade 完成）")

    auth_token = (auth_token or "").strip() or None
    ctx = dict(timing_ctx or {})
    t_submit = _now_m()
    try:
        resp = await _call_create_report_job(
            subject="math",
            submission_id=submission_id,
            auth_token=auth_token
        )
        job_id = str(resp.get("job_id") or "").strip()
        if not job_id:
            raise gr.Error("Report job creation failed: no job_id")
        ctx["report_job_submitted_m"] = float(t_submit)
        ctx["report_submit_ms"] = _ms_between(t_submit, _now_m())
        return (
            job_id,
            gr.update(interactive=False, value="正在生成报告..."),
            ctx,
        )
    except Exception as e:
        raise gr.Error(f"Generate report failed: {e}")




async def poll_job_status(
    job_id: str,
    report_job_id: str,
    report_id: str,
    session_id: str,
    upload_id: str,
    auth_token: Optional[str],
    timing_ctx: Dict[str, Any],
    page_progress: Dict[str, Any],
):
    """
    Polls the status of the job and updates the UI components.
    Returns: (stage1_html, stage2_html, timings_summary_md, timings_detail_md, grade_result_md, class_report_md, logs, report_job_id, report_id, btn_gen_report_interactive, timing_ctx)
    """
    ctx = dict(timing_ctx or {})
    now_m = _now_m()

    if not job_id:
        return (
            '<div style="color: gray">⏳ 等待中</div>',
            '<div style="color: gray">⏳ 等待中</div>',
            "",  # pages_progress_md
            gr.update(choices=[], value=None),  # page_no_dd
            "",
            "",
            "",  # grade_result_md
            "",  # class_report_md
            "",
            report_job_id or "",
            report_id or "",
            gr.update(interactive=False, value="生成学业报告"),
            ctx,
            dict(page_progress or {"total_pages": 0, "done_pages": 0, "page_context": {}}),
        )

    auth_token = (auth_token or "").strip() or None

    # Stage 1: Grade job (/grade async)
    grade_job: Dict[str, Any] = {}
    grade_status = "unknown"
    grade_err = None
    try:
        grade_job = await _call_job_status(job_id, auth_token=auth_token)
        grade_status = str(grade_job.get("status") or "unknown")
    except Exception as e:
        grade_err = str(e)

    # Update timing ctx for grade job
    if grade_status in {"processing", "queued", "running"} and ctx.get("grade_job_running_m") is None:
        ctx["grade_job_running_m"] = float(now_m)
    if grade_status in {"done", "failed"} and ctx.get("grade_job_done_m") is None:
        ctx["grade_job_done_m"] = float(now_m)
    ctx["grade_queue_wait_ms"] = _ms_between(ctx.get("grade_job_submitted_m"), ctx.get("grade_job_running_m"))
    worker_elapsed_ms = None
    if isinstance(grade_job, dict) and grade_job.get("elapsed_ms") is not None:
        try:
            worker_elapsed_ms = int(grade_job.get("elapsed_ms") or 0)
        except Exception:
            worker_elapsed_ms = None
    if worker_elapsed_ms is None:
        worker_elapsed_ms = _ms_between(ctx.get("grade_job_running_m"), ctx.get("grade_job_done_m"))
    ctx["grade_worker_elapsed_ms"] = worker_elapsed_ms
    ctx["grade_wall_ms"] = _ms_between(ctx.get("grade_job_submitted_m"), ctx.get("grade_job_done_m"))

    s1_html = '<div style="color: gray">⏳ grade 等待中</div>'
    if grade_err:
        s1_html = '<div style="color: red">❌ grade 查询失败</div>'
    elif grade_status in {"processing", "queued", "running"}:
        q_wait = _fmt_ms(ctx.get("grade_queue_wait_ms")) if ctx.get("grade_job_running_m") else "…"
        s1_html = f'<div style="color: blue">🔄 grade 处理中... (queue_wait={q_wait})</div>'
    elif grade_status == "done":
        s1_html = (
            f'<div style="color: green">✅ grade 已完成 '
            f"(wall={_fmt_ms(ctx.get('grade_wall_ms'))}, worker={_fmt_ms(ctx.get('grade_worker_elapsed_ms'))})</div>"
        )
    elif grade_status == "failed":
        s1_html = '<div style="color: red">❌ grade 失败</div>'

    # A-6: Multi-page progressive display (single job + partial output)
    p_state: Dict[str, Any] = dict(page_progress or {})
    total_pages = 0
    done_pages = 0
    page_summaries = []
    question_cards = []
    if isinstance(grade_job, dict):
        try:
            if grade_job.get("total_pages") is not None:
                p_state["total_pages"] = int(grade_job.get("total_pages") or 0)
            if grade_job.get("done_pages") is not None:
                p_state["done_pages"] = int(grade_job.get("done_pages") or 0)
            if isinstance(grade_job.get("page_summaries"), list):
                page_summaries = list(grade_job.get("page_summaries") or [])
            if isinstance(grade_job.get("question_cards"), list):
                question_cards = list(grade_job.get("question_cards") or [])
        except Exception:
            pass
    total_pages = int(p_state.get("total_pages") or 0)
    done_pages = int(p_state.get("done_pages") or 0)
    if isinstance(page_summaries, list) and page_summaries:
        context_map: Dict[str, Any] = {}
        for s in page_summaries:
            if not isinstance(s, dict):
                continue
            idx = s.get("page_index")
            try:
                idx_i = int(idx)
            except Exception:
                continue
            ids = s.get("wrong_item_ids")
            if isinstance(ids, list):
                context_map[str(idx_i)] = [str(x) for x in ids if str(x).strip()]
        p_state["page_context"] = context_map
        # If total_pages is still unknown, infer from max page_index.
        if not total_pages and context_map:
            try:
                total_pages = max(int(k) for k in context_map.keys()) + 1
                p_state["total_pages"] = int(total_pages)
            except Exception:
                pass

    pages_progress_md = ""
    if total_pages > 0:
        by_idx: Dict[int, Dict[str, Any]] = {}
        for s in page_summaries:
            if isinstance(s, dict) and s.get("page_index") is not None:
                try:
                    by_idx[int(s.get("page_index"))] = s
                except Exception:
                    continue
        lines: List[str] = []
        lines.append(f"#### 📄 逐页进度：`{done_pages}/{total_pages}`")
        for i in range(total_pages):
            s = by_idx.get(i)
            if isinstance(s, dict):
                wc = s.get("wrong_count")
                uc = s.get("uncertain_count")
                bc = s.get("blank_count")
                nr = "needs_review" if bool(s.get("needs_review")) else "ok"
                lines.append(
                    f"- 第 `{i+1}` 页：wrong=`{wc}` · uncertain=`{uc}` · blank=`{bc}` · `{nr}`"
                )
            else:
                lines.append(f"- 第 `{i+1}` 页：⏳ 处理中…")

        if question_cards:
            lines.append("")
            lines.append(f"#### 🧩 占位卡：`{len(question_cards)}`")
            by_page: Dict[int, Dict[str, int]] = {}
            for c in question_cards:
                if not isinstance(c, dict):
                    continue
                try:
                    pi = int(c.get("page_index") or 0)
                except Exception:
                    continue
                st = str(c.get("card_state") or "unknown")
                ans = str(c.get("answer_state") or "unknown")
                bucket = by_page.setdefault(
                    pi,
                    {
                        "placeholder": 0,
                        "verdict_ready": 0,
                        "review_pending": 0,
                        "review_ready": 0,
                        "review_failed": 0,
                        "blank": 0,
                    },
                )
                if st in bucket:
                    bucket[st] += 1
                else:
                    bucket["verdict_ready"] += 1
                if ans == "blank":
                    bucket["blank"] += 1
            for i in range(total_pages):
                if i not in by_page:
                    continue
                b = by_page[i]
                lines.append(
                    f"- 第 `{i+1}` 页：placeholder=`{b.get('placeholder', 0)}` · verdict_ready=`{b.get('verdict_ready', 0)}` · review_pending=`{b.get('review_pending', 0)}` · review_ready=`{b.get('review_ready', 0)}` · blank=`{b.get('blank', 0)}`"
                )
        pages_progress_md = "\n".join(lines)

    page_choices = [str(i + 1) for i in range(total_pages)] if total_pages > 0 else []
    page_no_dd_update = gr.update(
        choices=page_choices,
        value=str(min(done_pages, total_pages) or 1) if page_choices else None,
    )

    grade_result = grade_job.get("result") if isinstance(grade_job, dict) else None
    grade_report_md = ""
    # Always render grade result if available (Done or Failed with partial)
    if isinstance(grade_result, dict):
        try:
            grade_report_md = "\n".join(build_grade_report_sections(grade_result))
        except Exception:
            grade_report_md = ""

    # Best-effort: fetch qbank meta after grade completes (throttled retry).
    if grade_status == "done" and not isinstance(ctx.get("qbank_meta"), dict):
        last_try = ctx.get("qbank_meta_last_attempt_m")
        try:
            last_try_f = float(last_try) if last_try is not None else 0.0
        except Exception:
            last_try_f = 0.0
        if (now_m - last_try_f) >= 2.0:
            ctx["qbank_meta_last_attempt_m"] = float(now_m)
            qbank = await call_qbank_meta(str(session_id or ""), auth_token=auth_token)
            if isinstance(qbank, dict):
                # Keep it small: only store {meta,...} already trimmed by API.
                ctx["qbank_meta"] = qbank

    # Stage 2: Report job (Postgres-backed)
    r_job_id = str(report_job_id or "").strip()
    r_report_id = str(report_id or "").strip()
    
    report_job: Dict[str, Any] = {}
    report_status = "unknown"
    
    # Check button interactivity logic
    # Default: disabled (generating or not ready)
    btn_update = gr.update(interactive=False, value="生成学业报告")
    
    if grade_status == "done" and not r_job_id:
         # Grade done but report not started -> Enable button
         btn_update = gr.update(interactive=True, value="生成学业报告")

    if r_job_id:
        # Polling report job
        btn_update = gr.update(interactive=False, value="正在生成报告...")
        try:
            report_job = await _call_report_job(r_job_id, auth_token=auth_token)
            report_status = str(report_job.get("status") or "unknown")
            if not r_report_id:
                r_report_id = str(report_job.get("report_id") or "").strip()
        except Exception:
            pass

        s2_html = '<div style="color: gray">⏳ report 等待中</div>'
        if report_status in {"queued", "pending"}:
            s2_html = '<div style="color: gray">⏳ report 排队中</div>'
        elif report_status in {"processing", "running"}:
            s2_html = '<div style="color: blue">🔄 report 生成中...</div>'
        elif report_status == "done":
            s2_html = '<div style="color: green">✅ report 已生成</div>'
            btn_update = gr.update(interactive=True, value="重新生成报告")
        elif report_status == "failed":
            s2_html = '<div style="color: red">❌ report 失败</div>'
            btn_update = gr.update(interactive=True, value="重试生成报告")
    else:
         s2_html = '<div style="color: gray">⬜ 等待触发</div>'

    # Update timing ctx for report job
    if r_job_id:
        if report_status in {"processing", "running"} and ctx.get("report_job_running_m") is None:
            ctx["report_job_running_m"] = float(now_m)
        if report_status in {"done", "failed"} and ctx.get("report_job_done_m") is None:
            ctx["report_job_done_m"] = float(now_m)
    ctx["report_queue_wait_ms"] = _ms_between(ctx.get("report_job_submitted_m"), ctx.get("report_job_running_m"))
    ctx["report_wall_ms"] = _ms_between(ctx.get("report_job_submitted_m"), ctx.get("report_job_done_m"))

    class_report_md = ""
    if r_report_id and report_status == "done":
        try:
            report_row = await _call_get_report(r_report_id, auth_token=auth_token)
            content = (
                report_row.get("content") if isinstance(report_row, dict) else None
            )
            if isinstance(content, str) and content.strip():
                c = content.strip()
                if c.startswith("{") or c.startswith("["):
                    # JSON -> Markdown
                    try:
                        import json
                        obj = json.loads(c)
                        class_report_md = f"```json\n{json.dumps(obj, ensure_ascii=False, indent=2)}\n```"
                    except Exception:
                        class_report_md = c
                else:
                    class_report_md = c
        except Exception:
            pass

    timings_detail_md = _render_timing_panel_md(
        upload_id=str(upload_id or "").strip(),
        session_id=str(session_id or "").strip(),
        timing_ctx=ctx,
        grade_job=grade_job if isinstance(grade_job, dict) else None,
        report_job=report_job if isinstance(report_job, dict) else None,
    )
    timings_summary_md = _render_timing_summary_md(
        upload_id=str(upload_id or "").strip(),
        session_id=str(session_id or "").strip(),
        timing_ctx=ctx,
    )

    logs_lines: List[str] = []
    logs_lines.append(f"grade_job_id={job_id} status={grade_status}")
    if grade_err:
        logs_lines.append(f"grade_error={grade_err}")
    if r_job_id:
        logs_lines.append(f"report_job_id={r_job_id} status={report_status}")
    else:
        logs_lines.append("report_job_id=∅ (点击按钮触发)")
    if r_report_id:
        logs_lines.append(f"report_id={r_report_id}")
    logs = "\n".join(logs_lines)

    return (
        s1_html, 
        s2_html, 
        pages_progress_md,
        page_no_dd_update,
        timings_summary_md,
        timings_detail_md,
        grade_report_md, 
        class_report_md, 
        logs, 
        r_job_id, 
        r_report_id, 
        btn_update,
        ctx,
        p_state,
    )


def pick_page_for_tutoring(
    page_no: str,
    page_progress: Dict[str, Any],
) -> Tuple[Any, Any, Any]:
    """
    Demo helper for A-6:
    - User picks a page number and clicks "进入辅导（本页）"
    - We set a suggested starter prompt + attach context_item_ids (wrong_item_ids) for that page.
    """
    p = dict(page_progress or {})
    total_pages = int(p.get("total_pages") or 0)
    done_pages = int(p.get("done_pages") or 0)
    page_context = p.get("page_context") if isinstance(p.get("page_context"), dict) else {}

    s = str(page_no or "").strip()
    if not s or not s.isdigit():
        return gr.update(value=""), [], "请选择页号后再进入辅导。"
    page_index = int(s) - 1
    if page_index < 0:
        return gr.update(value=""), [], "页号不合法。"
    if total_pages and page_index >= total_pages:
        return gr.update(value=""), [], f"页号超出范围（共 {total_pages} 页）。"
    if done_pages and page_index >= done_pages:
        return (
            gr.update(value=""),
            [],
            f"第 {page_index+1} 页尚未完成（当前 {done_pages}/{total_pages}）。请稍后再试。",
        )

    ids = page_context.get(str(page_index)) if isinstance(page_context, dict) else None
    ids = [str(x) for x in (ids or []) if str(x).strip()]
    if not ids:
        return (
            gr.update(
                value=f"第 {page_index+1} 页似乎没有可用错题上下文（可能全对或尚未产出）。你也可以直接问“讲第几题”。"
            ),
            [],
            f"已选择第 {page_index+1} 页（但没有错题 item_ids）。",
        )

    return (
        gr.update(value=f"我们先从第 {page_index+1} 页的错题里选一题开始辅导。"),
        ids,
        f"已选择第 {page_index+1} 页（错题 {len(ids)} 个 item_ids）。",
    )






MAX_CANDIDATE_BUTTONS = 6


def _candidate_button_updates(candidates: List[str]) -> List[Any]:
    updates: List[Any] = []
    for idx in range(MAX_CANDIDATE_BUTTONS):
        if idx < len(candidates):
            updates.append(gr.update(value=str(candidates[idx]), visible=True))
        else:
            updates.append(gr.update(value="", visible=False))
    return updates


async def tutor_chat_logic(
    message: str,
    history: List[Dict[str, str]],
    session_id: str,
    subject: str,
    auth_token: Optional[str],
    context_item_ids: Optional[List[str | int]] = None,
) -> AsyncGenerator[Tuple[Any, ...], None]:
    """苏格拉底辅导逻辑（真实流式：后端 SSE 透传）"""
    history = history or []
    auth_token = (auth_token or "").strip() or None
    candidate_labels: List[str] = []
    candidate_button_updates = _candidate_button_updates(candidate_labels)
    tool_status = ""

    # 只允许批改后对话
    if not session_id:
        history.append(
            {
                "role": "assistant",
                "content": "请先上传图片并完成识别/批改，我需要基于这次作业来辅导。",
            }
        )
        yield "", history, candidate_labels, *candidate_button_updates, tool_status
        return

    # 先把用户消息显示出来
    history.append({"role": "user", "content": message})
    yield "", history, candidate_labels, *candidate_button_updates, tool_status

    # 插入“思考中...”占位，并在收到首条 chat 更新后替换为真实输出
    assistant_msg = {"role": "assistant", "content": "思考中... (0s)"}
    history.append(assistant_msg)
    yield "", history, candidate_labels, *candidate_button_updates, tool_status

    payload = {
        "history": [],
        "question": message,
        "subject": subject,
        "session_id": session_id,
        "context_item_ids": context_item_ids or [],
        "llm_model": None,
    }

    start = time.monotonic()
    current_event = ""
    last_rendered = ""
    last_focus_image_urls: List[str] = []

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{API_BASE_URL}/chat",
                json=payload,
                headers=_build_demo_headers(auth_token=auth_token),
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="ignore")
                    raise Exception(f"API 调用失败: {resp.status_code} - {body}")

                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue

                    # Update thinking clock on heartbeat
                    if current_event == "heartbeat":
                        elapsed = int(time.monotonic() - start)
                        if assistant_msg["content"].startswith("思考中"):
                            assistant_msg["content"] = f"思考中... ({elapsed}s)"
                            yield "", history, candidate_labels, *candidate_button_updates, tool_status
                        continue

                    if current_event == "error":
                        raise Exception(data)

                    if current_event == "chat":
                        try:
                            obj = json.loads(data)
                        except Exception:
                            continue
                        msgs = obj.get("messages") or []
                        raw_candidates = obj.get("question_candidates")
                        if isinstance(raw_candidates, list):
                            new_candidates = [str(c) for c in raw_candidates if c]
                            if new_candidates != candidate_labels:
                                candidate_labels = list(new_candidates)
                                candidate_button_updates = _candidate_button_updates(
                                    candidate_labels
                                )
                        focus_urls = obj.get("focus_image_urls") or []
                        if isinstance(focus_urls, list):
                            focus_urls = [str(u) for u in focus_urls if u]
                        else:
                            focus_urls = []
                        if focus_urls and focus_urls != last_focus_image_urls:
                            last_focus_image_urls = list(focus_urls)
                            # Insert image bubble only once per image set (first time or when switching focus).
                            # Avoid spamming the same image on every user turn.
                            already_in_history = False
                            try:
                                for u in focus_urls[:2]:
                                    if any(
                                        u in str(m.get("content") or "")
                                        for m in history
                                        if isinstance(m, dict)
                                    ):
                                        already_in_history = True
                                        break
                            except Exception:
                                already_in_history = False
                            if not already_in_history:
                                md = "\n".join(
                                    [f"![题目图/切片]({u})" for u in focus_urls[:2]]
                                )
                                history.insert(
                                    max(0, len(history) - 1),
                                    {
                                        "role": "assistant",
                                        "content": f"我将参考你这题的图片/切片：\n\n{md}",
                                    },
                                )
                                yield "", history, candidate_labels, *candidate_button_updates, tool_status
                        # Find latest assistant message content
                        latest = ""
                        for m in reversed(msgs):
                            if m.get("role") == "assistant":
                                latest = m.get("content") or ""
                                break
                        if latest and latest != last_rendered:
                            assistant_msg["content"] = latest
                            last_rendered = latest
                            yield "", history, candidate_labels, *candidate_button_updates, tool_status
                        continue

                    if current_event == "tool_progress":
                        try:
                            obj = json.loads(data)
                        except Exception:
                            obj = {}
                        tool_name = str(obj.get("tool") or obj.get("name") or "tool")
                        status = str(obj.get("status") or "running")
                        tool_status = f"🔧 工具进度：{tool_name} · {status}"
                        yield "", history, candidate_labels, *candidate_button_updates, tool_status
                        continue

                    if current_event == "done":
                        break

    except Exception as e:
        assistant_msg["content"] = f"系统错误：{str(e)}"
        yield "", history, candidate_labels, *candidate_button_updates, tool_status
        return


async def _candidate_chat_logic(
    idx: int,
    history: List[Dict[str, str]],
    session_id: str,
    subject: str,
    auth_token: Optional[str],
    candidates: List[str],
) -> AsyncGenerator[Tuple[Any, ...], None]:
    text = ""
    if isinstance(candidates, list) and 0 <= idx < len(candidates):
        text = str(candidates[idx])
    if not text:
        updates = _candidate_button_updates(candidates or [])
        yield "", (history or []), (candidates or []), *updates, ""
        return
    async for update in tutor_chat_logic(
        text, history, session_id, subject, auth_token
    ):
        yield update


def _make_candidate_handler(idx: int):
    async def _handler(
        history: List[Dict[str, str]],
        session_id: str,
        subject: str,
        auth_token: Optional[str],
        candidates: List[str],
    ) -> AsyncGenerator[Tuple[Any, ...], None]:
        async for update in _candidate_chat_logic(
            idx, history, session_id, subject, auth_token, candidates
        ):
            yield update

    return _handler


async def tutor_chat_logic_demo2(
    message: str,
    history: List[Dict[str, str]],
    session_id: str,
    subject: str,
    auth_token: Optional[str],
    context_item_ids: Optional[List[str | int]] = None,
) -> AsyncGenerator[Tuple[Any, ...], None]:
    """
    Demo UI 2.0 adapter:
    - Reuse the full tutor_chat_logic (which also yields candidate button updates),
      but only surface (msg, history, tool_status) in this simplified tab.
    """
    async for update in tutor_chat_logic(
        message,
        history,
        session_id,
        subject,
        auth_token,
        context_item_ids=context_item_ids,
    ):
        msg_value = update[0] if len(update) > 0 else ""
        hist_value = update[1] if len(update) > 1 else (history or [])
        tool_status = update[-1] if update else ""
        yield msg_value, hist_value, tool_status


def create_demo():
    """创建 Gradio Demo 2.0 (Workflow Console)"""
    blocks_kwargs: Dict[str, Any] = {"title": "作业检查大师 (Homework Agent)"}
    supports_head = "head" in inspect.signature(gr.Blocks.__init__).parameters
    if supports_head:
        blocks_kwargs["head"] = MATHJAX_HEAD

    with gr.Blocks(**blocks_kwargs) as demo:
        # Older gradio: no `head` support
        if not supports_head:
            gr.HTML(MATHJAX_HEAD)

        auth_token_state = gr.State(value=DEMO_AUTH_TOKEN or "")
        auth_user_id_state = gr.State(value="")
        job_id_state = gr.State(value="")
        session_id_state = gr.State(value="")
        upload_id_state = gr.State(value="")
        report_job_id_state = gr.State(value="")
        report_id_state = gr.State(value="")
        timing_ctx_state = gr.State(value={})
        page_progress_state = gr.State(value={"total_pages": 0, "done_pages": 0, "page_context": {}})
        chat_context_item_ids_state = gr.State(value=[])

        # Auth helpers (kept local to create_demo for simplicity).
        def _mask_token(token: str) -> str:
            t = (token or "").strip()
            if not t:
                return ""
            if len(t) <= 18:
                return t[:6] + "…" + t[-3:]
            return f"{t[:10]}…{t[-6:]}"

        def _auth_status_md(token: str, user_id: str) -> str:
            t, uid = (token or "").strip(), (user_id or "").strip()
            if t:
                return (
                    f"- Auth: ✅ 已登录（Bearer `{_mask_token(t)}`）\n"
                    f"- user_id: `{uid or 'unknown'}`\n"
                )
            return (
                f"- Auth: ⚠️ 未登录（使用开发模式 header: `X-User-Id={DEMO_USER_ID}`）\n"
            )

        # ... (Redefining auth handlers for completeness as they were local functions)
        def _auth_login(email, password, cur_token, cur_uid):
            try:
                token, uid = supabase_sign_in_with_password(
                    (email or "").strip(), (password or "").strip()
                )
                return token, uid, _auth_status_md(token, uid)
            except Exception as e:
                return (
                    cur_token,
                    cur_uid,
                    f"❌ 登录失败：{str(e)}\n\n{_auth_status_md(cur_token, cur_uid)}",
                )

        def _auth_signup(email, password, cur_token, cur_uid):
            try:
                token, uid = supabase_sign_up(
                    (email or "").strip(), (password or "").strip()
                )
                if token:
                    return (
                        token,
                        (uid or ""),
                        f"✅ 注册成功\n\n{_auth_status_md(token, uid or '')}",
                    )
                return (
                    cur_token,
                    cur_uid,
                    f"✅ 注册成功（需邮箱确认）\n\n{_auth_status_md(cur_token, cur_uid)}",
                )
            except Exception as e:
                return (
                    cur_token,
                    cur_uid,
                    f"❌ 注册失败：{str(e)}\n\n{_auth_status_md(cur_token, cur_uid)}",
                )

        def _auth_logout():
            return "", "", _auth_status_md("", "")

        gr.Markdown("# 🎓 作业检查大师 (Homework Agent)")

        # Auth Accordion
        with gr.Accordion("🔐 登录/注册（Supabase Auth）", open=False):
            with gr.Row():
                auth_email = gr.Textbox(label="Email")
                auth_password = gr.Textbox(label="Password", type="password")
            with gr.Row():
                btn_login = gr.Button("登录", variant="primary")
                btn_signup = gr.Button("注册", variant="secondary")
                btn_logout = gr.Button("退出登录", variant="secondary")
            auth_status = gr.Markdown(value=_auth_status_md(DEMO_AUTH_TOKEN, ""))

            btn_login.click(
                _auth_login,
                [auth_email, auth_password, auth_token_state, auth_user_id_state],
                [auth_token_state, auth_user_id_state, auth_status],
            )
            btn_signup.click(
                _auth_signup,
                [auth_email, auth_password, auth_token_state, auth_user_id_state],
                [auth_token_state, auth_user_id_state, auth_status],
            )
            btn_logout.click(
                _auth_logout, None, [auth_token_state, auth_user_id_state, auth_status]
            )


        with gr.Tabs():
                with gr.Tab("🚀 工作台 (Workflow Console)"):
                    # ================= Input Area =================
                    with gr.Row():
                        with gr.Column(scale=1):
                            file_kwargs: Dict[str, Any] = {
                                "label": "📤 上传图片（可多选）",
                                # Allow HEIC/HEIF/PDF explicitly (some environments don't classify them as "image").
                                "file_types": ["image", ".heic", ".heif", ".pdf"],
                                "height": 200,
                            }
                            if (
                                "file_count"
                                in inspect.signature(gr.File.__init__).parameters
                            ):
                                file_kwargs["file_count"] = "multiple"
                            input_img = gr.File(**file_kwargs)
                        # Simplified: Hardcoded defaults (math/doubao/ark)
                        # subject_dropdown = gr.Dropdown(...) -> Removed
                        # provider_dropdown = gr.Dropdown(...) -> Removed
                        # llm_dropdown = gr.Dropdown(...) -> Removed
                        
                        submit_btn = gr.Button("🚀 提交作业 (Async)", variant="primary")
                        submission_status_md = gr.Markdown("准备就绪")

                # ================= Monitor Area (Hidden Initially) =================
                with gr.Group(visible=False) as monitor_group:
                    gr.Markdown("### 📊 实时流水线 (Pipeline Monitor)")
                    with gr.Row():
                        s1_html = gr.HTML(
                            label="Stage 1: Grade",
                            value='<div style="color: gray">⏳ 等待中</div>',
                        )
                        s2_html = gr.HTML(
                            label="Stage 2: Report",
                            value='<div style="color: gray">⏳ 等待中</div>',
                        )

                    pages_progress_md = gr.Markdown(value="")
                    with gr.Row():
                        page_no_dd = gr.Dropdown(
                            label="选择页（用于进入辅导）",
                            choices=[],
                            value=None,
                            interactive=True,
                        )
                        btn_pick_page = gr.Button("进入辅导（本页）", variant="secondary")
                    tutor_scope_md = gr.Markdown(value="")
                    
                    btn_gen_report = gr.Button("生成学业报告", variant="secondary", interactive=False)
                    timings_summary_md = gr.Markdown(value="")
                    with gr.Accordion("高级：调试指标（默认隐藏）", open=False):
                        timings_detail_md = gr.Markdown(value="")
                    logs_box = gr.Textbox(
                        label="System Logs", lines=5, interactive=False
                    )

                # ================= Result Area =================
                # Split into Tabs for persistence
                with gr.Tabs():
                    with gr.Tab("批改结果"):
                        grade_result_md = gr.Markdown(label="Grade Result")
                    with gr.Tab("学业报告"):
                        class_report_md = gr.Markdown(label="Class Report")

                # Chatbot for follow-up
                gr.Markdown("### 💬 辅导对话")
                chatbot_kwargs: Dict[str, Any] = {"height": 400, "label": "AI 助教"}
                if "type" in inspect.signature(gr.Chatbot.__init__).parameters:
                    chatbot_kwargs["type"] = "messages"
                chatbot = gr.Chatbot(**chatbot_kwargs)
                msg = gr.Textbox(label="你的问题")
                tool_status_md = gr.Markdown(value="")

                # Logic Wiring
                # 1. Submit
                submit_btn.click(
                    fn=submit_job_handler,
                    inputs=[
                        input_img,
                        auth_token_state,
                    ],
                    outputs=[
                        job_id_state,
                        session_id_state,
                        upload_id_state,
                        report_job_id_state,
                        report_id_state,
                        monitor_group,
                        submission_status_md,
                        logs_box,
                        timings_summary_md,
                        timings_detail_md,
                        grade_result_md,
                        class_report_md,
                        btn_gen_report,
                        timing_ctx_state,
                        page_progress_state,
                        chat_context_item_ids_state,
                    ],
                )

                # 2. Manual Report Generation
                btn_gen_report.click(
                    fn=generate_report_handler,
                    inputs=[upload_id_state, auth_token_state, timing_ctx_state],
                    outputs=[
                        report_job_id_state,
                        btn_gen_report,
                        timing_ctx_state,
                    ]
                )

                # 3. Polling (Timer)
                # Poll every 2 seconds
                timer = gr.Timer(2.0)
                timer.tick(
                    fn=poll_job_status,
                    inputs=[
                        job_id_state,
                        report_job_id_state,
                        report_id_state,
                        session_id_state,
                        upload_id_state,
                        auth_token_state,
                        timing_ctx_state,
                        page_progress_state,
                    ],
                    outputs=[
                        s1_html,
                        s2_html,
                        pages_progress_md,
                        page_no_dd,
                        timings_summary_md,
                        timings_detail_md,
                        grade_result_md,
                        class_report_md,
                        logs_box,
                        report_job_id_state,
                        report_id_state,
                        btn_gen_report,
                        timing_ctx_state,
                        page_progress_state,
                    ],
                )

                btn_pick_page.click(
                    fn=pick_page_for_tutoring,
                    inputs=[page_no_dd, page_progress_state],
                    outputs=[msg, chat_context_item_ids_state, tutor_scope_md],
                )

                msg.submit(
                    fn=tutor_chat_logic_demo2,
                    inputs=[
                        msg,
                        chatbot,
                        session_id_state,
                        gr.State("math"), # Hardcoded subject
                        auth_token_state,
                        chat_context_item_ids_state,
                    ],
                    outputs=[msg, chatbot, tool_status_md],
                )



    return demo


if __name__ == "__main__":
    # 设置环境变量
    os.environ["no_proxy"] = "localhost,127.0.0.1,0.0.0.0"
    os.environ["GRADIO_API_INFO"] = "0"  # 禁用API信息获取以避免兼容性问题

    # 创建并启动 Demo
    demo = create_demo()
    demo.queue().launch(server_name="127.0.0.1", server_port=7890, show_error=True)
