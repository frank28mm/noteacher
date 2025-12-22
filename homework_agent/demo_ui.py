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

from typing import List, Dict, Any, Optional, AsyncGenerator, Tuple
from homework_agent.models.schemas import Subject, VisionProvider, WrongItem, Message, ImageRef
from homework_agent.services.vision import VisionClient
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
    os.getenv("DEMO_GRADE_TIMEOUT_SECONDS", str(_settings.grade_completion_sla_seconds + 60))
)
DEMO_USER_ID = (os.getenv("DEMO_USER_ID") or os.getenv("DEV_USER_ID") or "dev_user").strip() or "dev_user"
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
    upload = done_line("图片上传完成") if stage not in {"uploading"} else doing_line("图片上传中…")
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


def upload_to_backend(file_path: str, *, session_id: Optional[str], auth_token: Optional[str]) -> Dict[str, Any]:
    """上传文件到后端 /uploads，并返回 {upload_id, page_image_urls, ...}。"""
    if not file_path or not os.path.exists(file_path):
        raise ValueError("文件不存在")

    # 检查文件大小 (<20MB)
    file_size = os.path.getsize(file_path)
    if file_size > 20 * 1024 * 1024:
        raise ValueError(f"文件超过 20MB: {file_size / 1024 / 1024:.2f}MB")

    filename = os.path.basename(file_path)
    content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    params: Dict[str, str] = {}
    if session_id:
        params["session_id"] = str(session_id)

    with open(file_path, "rb") as f:
        files = {"file": (filename, f, content_type)}
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
    md = f"## 📊 评分结果\n\n"
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
            qtext = item.get('question_content') or item.get('question') or 'N/A'
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

    if result.get('warnings'):
        md += "\n### ⚠️ 警告\n"
        for warning in result['warnings']:
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
            if meta.get('vision_used_base64_fallback') is not None:
                md += f"- Vision base64 兜底: {meta.get('vision_used_base64_fallback')}\n"
            md += f"- LLM provider: {meta.get('llm_provider_used', meta.get('llm_provider_requested', 'N/A'))}\n"
            if meta.get('llm_used_fallback') is not None:
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
    vision_raw = re.sub(r"---OCR[识识]?别?原文---\s*", "", vision_raw, flags=re.IGNORECASE).strip()
    vision_raw = re.sub(r"---END_OCR_TEXT---\s*", "", vision_raw, flags=re.IGNORECASE).strip()
    vision_raw = re.sub(r"---VISUAL_FACTS_JSON---.*", "", vision_raw, flags=re.DOTALL).strip()
    vision_raw = re.sub(r"<<<[A-Z_]+>>>\s*", "", vision_raw).strip()
    vision_raw = re.sub(r"<<<END_[A-Z_]+>>>\s*", "", vision_raw).strip()
    
    # Strip JSON blocks that might appear at the end (e.g., visual_facts JSON)
    vision_raw = re.sub(r"```json\s*\{.*", "", vision_raw, flags=re.DOTALL).strip()
    vision_raw = re.sub(r"\{[\s\n]*\"questions\":\s*\{.*", "", vision_raw, flags=re.DOTALL).strip()
    
    # Convert LaTeX delimiters from \( \) to $ $ for MathJax rendering
    # First handle escaped backslashes: \\( \\) -> $ $
    vision_raw = re.sub(r"\\\(", "$", vision_raw)
    vision_raw = re.sub(r"\\\)", "$", vision_raw)
    # Also handle display math: \[ \] -> $$ $$
    vision_raw = re.sub(r"\\\[", "$$", vision_raw)
    vision_raw = re.sub(r"\\\]", "$$", vision_raw)
    
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
            translated = p.replace("is vertical", "是竖直的").replace("is horizontal", "是水平的")
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
            segs.append("夹在 " + " 与 ".join([str(x) for x in between if str(x).strip()]))
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
        qnum = item.get("question_number") or item.get("question_index") or item.get("id")
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

    if correct_qns:
        correct_count = len(correct_qns)
    elif result.get("total_items") is not None and wrong_count is not None:
        correct_count = max(0, int(result.get("total_items") or 0) - int(wrong_count or 0))
    else:
        correct_count = None

    wrong_total = wrong_count if wrong_count is not None else len(wrong_items)
    if correct_count is None:
        header += f"✅ 正确：待确认 | ❌ 错误：{wrong_total} 道\n"
    else:
        header += f"✅ 正确：{correct_count} 道 | ❌ 错误：{wrong_total} 道\n"
    sections.append(header)

    if wrong_items:
        md = "---\n"
        for item in wrong_items:
            qnum = item.get("question_number") or item.get("question_index") or "N/A"
            qtext = _repair_latex_escapes(item.get("question_content") or item.get("question") or "N/A")
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

    if correct_qns:
        md = "---\n"
        for qn in correct_qns:
            q_data = questions_map.get(str(qn)) or {}
            basis = q_data.get("judgment_basis") or []
            if basis and isinstance(basis, list):
                md += f"<details><summary>✅ 题 {qn} ▶ 点击查看 AI 识别依据</summary>\n\n"
                for b in basis:
                    if isinstance(b, str) and b.strip():
                        md += f"- {_repair_latex_escapes(b.strip())}\n"
                md += "</details>\n\n"
            else:
                md += f"✅ 题 {qn}\n\n"
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
        response = await client.post(
            f"{API_BASE_URL}/grade",
            json=payload,
            headers=_build_demo_headers(auth_token=auth_token),
        )

    if response.status_code != 200:
        raise Exception(f"API 调用失败: {response.status_code} - {response.text}")

    return response.json()


async def call_grade_progress(session_id: str, *, auth_token: Optional[str]) -> Optional[Dict[str, Any]]:
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


async def call_qbank_meta(session_id: str, *, auth_token: Optional[str]) -> Optional[Dict[str, Any]]:
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


async def grade_homework_logic(img_path, subject, provider, llm_provider, auth_token, history):
    """批改作业主逻辑（流式状态更新）：上传 → Vision → 批改 → 渲染到 Chat"""
    # gr.File returns path string or object with .name
    if hasattr(img_path, "name"):
        img_path = img_path.name

    if not img_path:
        yield [{"role": "assistant", "content": "❌ 请先上传图片文件。"}], None, None, "❌ 未选择文件"
        return

    session_id = f"demo_{uuid.uuid4().hex[:8]}"
    started = time.monotonic()
    auth_token = (auth_token or "").strip() or None
    history = []
    image_added = False

    try:
        # Step 1: 上传到后端 /uploads（后端落 Supabase Storage，返回 upload_id）
        yield history, session_id, None, _render_stage_lines("uploading", int(time.monotonic() - started))

        upload_task = asyncio.create_task(
            asyncio.to_thread(upload_to_backend, img_path, session_id=session_id, auth_token=auth_token)
        )
        while not upload_task.done():
            await asyncio.sleep(0.15)
            yield history, session_id, None, _render_stage_lines(
                "uploading", int(time.monotonic() - started)
            )

        upload_resp = await upload_task
        upload_id = str(upload_resp.get("upload_id") or "").strip()
        page_urls = upload_resp.get("page_image_urls") or []
        if not upload_id:
            history[-1]["content"] = "❌ 上传失败，未获取到 upload_id。"
            yield history, session_id, None, "❌ 上传失败"
            return
        if not (isinstance(page_urls, list) and page_urls):
            history[-1]["content"] = "❌ 上传失败，未获取到 page_image_urls。"
            yield history, session_id, None, "❌ 上传失败"
            return

        page_url = str(page_urls[0])
        if page_url and not image_added:
            history.append(
                {
                    "role": "user",
                    "content": f"![原图]({page_url})\n\n请帮我批改这份作业",
                }
            )
            image_added = True
        yield history, session_id, page_url, _render_stage_lines(
            "accepted", int(time.monotonic() - started)
        )

        # Step 2: 调用后端 /grade（upload_id -> 后端反查 images）
        grade_task = asyncio.create_task(
            call_grade_api(
                upload_id=upload_id,
                subject=subject,
                provider=provider,
                llm_provider=llm_provider,
                session_id=session_id,
                auth_token=auth_token,
            )
        )

        last_progress_stage = "accepted"
        while not grade_task.done():
            await asyncio.sleep(0.4)
            p = await call_grade_progress(session_id, auth_token=auth_token)
            if isinstance(p, dict):
                stage = str(p.get("stage") or "").strip() or last_progress_stage
                last_progress_stage = stage
            else:
                stage = last_progress_stage
            yield history, session_id, page_url, _render_stage_lines(
                stage, int(time.monotonic() - started)
            )

        result = await grade_task
        if page_url and not image_added:
            history.append(
                {
                    "role": "user",
                    "content": f"![原图]({page_url})\n\n请帮我批改这份作业",
                }
            )
            image_added = True
        sections = build_grade_report_sections(result)
        for section in sections:
            history.append({"role": "assistant", "content": ""})
            for chunk in _chunk_text_for_stream(section):
                history[-1]["content"] += chunk
                yield history, session_id, page_url, _render_stage_lines(
                    "done", int(time.monotonic() - started)
                )
                await asyncio.sleep(0.02)
        return

    except ValueError as e:
        history[-1]["content"] = f"❌ {str(e)}"
        yield history, session_id, None, f"❌ 失败：{e}"
        return
    except Exception as e:
        err_msg = str(e)
        if "20040" in err_msg:
            err_msg += "\n\n提示：模型无法下载该 URL，建议检查图片是否可公开访问"
        history[-1]["content"] = f"❌ 系统错误：{err_msg}"
        yield history, session_id, None, f"❌ 失败：{err_msg}"
        return


async def vision_debug_logic(img_path, provider, auth_token):
    """直接调用 Vision 模型，返回原始识别文本（debug_vision 的 UI 化版本）"""
    # gr.File returns path string or object with .name
    if hasattr(img_path, "name"):
        img_path = img_path.name

    if not img_path:
        return "**错误**：请上传图片文件。", ""

    auth_token = (auth_token or "").strip() or None
    try:
        gr.Info("📤 上传到后端 /uploads ...")
        # Vision 调试也走后端 /uploads（统一存储路径、便于后续复用 URL/base64 兜底逻辑）
        upload_resp = await asyncio.to_thread(upload_to_backend, img_path, session_id=None, auth_token=auth_token)
        urls = upload_resp.get("page_image_urls") or []
        if not (isinstance(urls, list) and urls):
            return "**错误**：上传失败，未获取到 URL。", ""
        img_url = str(urls[0])
        gr.Info(f"✅ 上传成功，URL: {img_url} (upload_id={upload_resp.get('upload_id')})")

        # 调用 Vision
        client = VisionClient()
        prompt = "请详细识别并提取这张图片中的所有题目、学生的解答过程和最终答案。请按题目顺序列出。"
        gr.Info("👁️ 正在调用 Vision 模型...")
        # VisionClient.analyze 是同步方法，放线程池避免阻塞
        result = await asyncio.to_thread(
            client.analyze,
            images=[ImageRef(url=img_url)],
            prompt=prompt,
            provider=VisionProvider(provider),
        )
        md = f"**上传 URL**: {img_url}\n\n"
        md += f"**模型**: {provider}\n\n"
        md += "### Vision 原始识别文本\n"
        md += f"```\n{result.text}\n```"
        return md, img_url
    except Exception as e:
        return f"**系统错误**：{e}", ""


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
) -> AsyncGenerator[Tuple[Any, ...], None]:
    """苏格拉底辅导逻辑（真实流式：后端 SSE 透传）"""
    history = history or []
    auth_token = (auth_token or "").strip() or None
    candidate_labels: List[str] = []
    candidate_button_updates = _candidate_button_updates(candidate_labels)
    tool_status = ""

    # 只允许批改后对话
    if not session_id:
        history.append({"role": "assistant", "content": "请先上传图片并完成识别/批改，我需要基于这次作业来辅导。"})
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
        "context_item_ids": [],
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
                                candidate_button_updates = _candidate_button_updates(candidate_labels)
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
                                    if any(u in str(m.get("content") or "") for m in history if isinstance(m, dict)):
                                        already_in_history = True
                                        break
                            except Exception:
                                already_in_history = False
                            if not already_in_history:
                                md = "\n".join([f"![题目图/切片]({u})" for u in focus_urls[:2]])
                                history.insert(
                                    max(0, len(history) - 1),
                                    {"role": "assistant", "content": f"我将参考你这题的图片/切片：\n\n{md}"},
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
    async for update in tutor_chat_logic(text, history, session_id, subject, auth_token):
        yield update


def _make_candidate_handler(idx: int):
    async def _handler(
        history: List[Dict[str, str]],
        session_id: str,
        subject: str,
        auth_token: Optional[str],
        candidates: List[str],
    ) -> AsyncGenerator[Tuple[Any, ...], None]:
        async for update in _candidate_chat_logic(idx, history, session_id, subject, auth_token, candidates):
            yield update

    return _handler


def create_demo():
    """创建 Gradio Demo"""
    blocks_kwargs: Dict[str, Any] = {"title": "作业检查大师 (Homework Agent)"}
    supports_head = "head" in inspect.signature(gr.Blocks.__init__).parameters
    if supports_head:
        blocks_kwargs["head"] = MATHJAX_HEAD

    with gr.Blocks(**blocks_kwargs) as demo:
        # Older gradio: no `head` support, inject MathJax via HTML component.
        if not supports_head:
            gr.HTML(MATHJAX_HEAD)

        auth_token_state = gr.State(value=DEMO_AUTH_TOKEN or "")
        auth_user_id_state = gr.State(value="")

        def _mask_token(token: str) -> str:
            t = (token or "").strip()
            if not t:
                return ""
            if len(t) <= 18:
                return t[:6] + "…" + t[-3:]
            return f"{t[:10]}…{t[-6:]}"

        def _auth_status_md(token: str, user_id: str) -> str:
            t = (token or "").strip()
            uid = (user_id or "").strip()
            if t:
                return f"- Auth: ✅ 已登录（Bearer `{_mask_token(t)}`）\n- user_id: `{uid or 'unknown'}`\n"
            return f"- Auth: ⚠️ 未登录（使用开发模式 header: `X-User-Id={DEMO_USER_ID}`）\n"

        def _auth_login(email: str, password: str, cur_token: str, cur_uid: str):
            try:
                token, uid = supabase_sign_in_with_password((email or "").strip(), (password or "").strip())
                return token, uid, _auth_status_md(token, uid)
            except Exception as e:
                return cur_token, cur_uid, f"❌ 登录失败：{str(e)}\n\n{_auth_status_md(cur_token, cur_uid)}"

        def _auth_signup(email: str, password: str, cur_token: str, cur_uid: str):
            try:
                token, uid = supabase_sign_up((email or "").strip(), (password or "").strip())
                if token:
                    return token, (uid or ""), f"✅ 注册成功并已登录\n\n{_auth_status_md(token, uid or '')}"
                # Email confirmation required / no session returned.
                return cur_token, cur_uid, f"✅ 注册成功（可能需要邮箱确认，暂未获得 access_token）\n\n{_auth_status_md(cur_token, cur_uid)}"
            except Exception as e:
                return cur_token, cur_uid, f"❌ 注册失败：{str(e)}\n\n{_auth_status_md(cur_token, cur_uid)}"

        def _auth_logout():
            return "", "", _auth_status_md("", "")

        gr.Markdown("""
        # 🎓 作业检查大师 (Homework Agent)

        ### 🔄 真实业务场景模拟
        - **Step 1**: 上传本地文件 → 后端 `/api/v1/uploads`
        - **Step 2**: 后端写入 Supabase Storage（权威原图），返回 `upload_id` + `page_image_urls`
        - **Step 3**: 调用后端 `/api/v1/grade`（携带 `upload_id`，后端反查 images 并批改）
        - **Step 4**: 调用后端 `/api/v1/chat`（SSE）进行苏格拉底辅导

        ### 📝 使用说明
        - ✅ 支持格式：JPG、PNG、WebP
        - 🗂️ 支持：HEIC/HEIF 自动转 JPEG，PDF 自动拆前 8 页
        - ⚠️ 文件大小：≤ 20MB
        - 📐 尺寸：Qwen3 最小边 ≥28px，Doubao 最小边 ≥14px
        - 🌍 URL 要求：必须是公网可访问 (禁止 localhost/内网)
        - 🤖 模型选择：Doubao（默认，仅 URL） / Qwen3（备用，支持 URL+base64）
        """)

        with gr.Accordion("🔐 登录/注册（Supabase Auth，P0-阶段B）", open=False):
            gr.Markdown(
                "说明：\n"
                "- 登录后，demo 会用 `Authorization: Bearer <access_token>` 调用后端；后端会验证 JWT 并以 token 内的 `user.id` 作为可信 `user_id`。\n"
                "- 未登录时，demo 会用开发模式 `X-User-Id`（仅用于本地调试；上线前会移除）。\n"
            )
            with gr.Row():
                auth_email = gr.Textbox(label="Email", placeholder="you@example.com")
                auth_password = gr.Textbox(label="Password", type="password", placeholder="••••••••")
            with gr.Row():
                btn_login = gr.Button("登录", variant="primary")
                btn_signup = gr.Button("注册", variant="secondary")
                btn_logout = gr.Button("退出登录", variant="secondary")
            auth_status = gr.Markdown(value=_auth_status_md(DEMO_AUTH_TOKEN, ""))

            btn_login.click(
                fn=_auth_login,
                inputs=[auth_email, auth_password, auth_token_state, auth_user_id_state],
                outputs=[auth_token_state, auth_user_id_state, auth_status],
                show_progress=True,
            )
            btn_signup.click(
                fn=_auth_signup,
                inputs=[auth_email, auth_password, auth_token_state, auth_user_id_state],
                outputs=[auth_token_state, auth_user_id_state, auth_status],
                show_progress=True,
            )
            btn_logout.click(
                fn=_auth_logout,
                inputs=None,
                outputs=[auth_token_state, auth_user_id_state, auth_status],
                show_progress=False,
            )

        with gr.Tabs():
            # ========== Tab 1: 统一对话 ==========
            with gr.Tab("💬 对话"):
                gr.Markdown(
                    "上传图片后系统会自动识别与批改，并把**识别原文 + AI 识别依据 + 批改结果**展示在对话框里。\n\n"
                    "- 你可以直接说：`讲讲第23题` / `再讲讲19题` / `第2题有没有更简便的方法？`\n"
                    "- 系统会尝试根据题号在本次 session 中定位对应题目。\n"
                )
                with gr.Row():
                    with gr.Column(scale=1):
                        input_img = gr.File(
                            label="📤 上传图片",
                            file_types=["image"],
                            height=260,
                        )
                        subject_dropdown = gr.Dropdown(
                            choices=["math", "english"],
                            value="math",
                            label="📚 学科 (Subject)",
                        )
                        provider_dropdown = gr.Dropdown(
                            choices=["doubao", "qwen3"],
                            value="doubao",
                            label="🤖 视觉模型 (Vision)",
                        )
                        llm_dropdown = gr.Dropdown(
                            choices=["ark", "silicon"],
                            value="ark",
                            label="🧠 批改模型 (LLM)",
                            info="ark=doubao-seed, silicon=qwen3-max",
                        )
                        grade_btn = gr.Button("🚀 开始识别/批改", variant="primary")
                        status_md = gr.Markdown(label="状态")
                        session_id_state = gr.State()
                        image_url_state = gr.State()

                    with gr.Column(scale=1):
                        chatbot = gr.Chatbot(
                            label="💬 对话",
                            height=520,
                            latex_delimiters=[
                                {"left": "$$", "right": "$$", "display": True},
                                {"left": "$", "right": "$", "display": False},
                            ],
                        )
                        tool_status_md = gr.Markdown(label="🔧 工具进度", value="")
                        candidates_state = gr.State(value=[])
                        with gr.Row():
                            candidate_buttons = [
                                gr.Button(visible=False) for _ in range(MAX_CANDIDATE_BUTTONS)
                            ]
                        msg = gr.Textbox(
                            label="💭 你的问题",
                            placeholder="这道题为什么错了？应该怎么思考？",
                        )
                        clear_btn = gr.Button("🗑️ 清除历史")

                grade_btn.click(
                    fn=grade_homework_logic,
                    inputs=[input_img, subject_dropdown, provider_dropdown, llm_dropdown, auth_token_state, chatbot],
                    outputs=[chatbot, session_id_state, image_url_state, status_md],
                )

                # 发送消息
                msg.submit(
                    fn=tutor_chat_logic,
                    inputs=[msg, chatbot, session_id_state, subject_dropdown, auth_token_state],
                    outputs=[msg, chatbot, candidates_state, *candidate_buttons, tool_status_md],
                )

                for idx, btn in enumerate(candidate_buttons):
                    btn.click(
                        fn=_make_candidate_handler(idx),
                        inputs=[chatbot, session_id_state, subject_dropdown, auth_token_state, candidates_state],
                        outputs=[msg, chatbot, candidates_state, *candidate_buttons, tool_status_md],
                    )

                # 清除历史
                clear_btn.click(
                    fn=lambda: ([], "", [], *_candidate_button_updates([]), "", None, ""),
                    inputs=None,
                    outputs=[chatbot, msg, candidates_state, *candidate_buttons, tool_status_md, session_id_state, status_md],
                    queue=False,
                )

            # ========== Tab 2: Vision 调试 ==========
            with gr.Tab("👁️ Vision 调试"):
                with gr.Row():
                    with gr.Column(scale=1):
                        vision_input = gr.File(
                            label="上传图片 (JPG/PNG/HEIC/PDF)",
                            file_types=["image", "pdf"],
                            height=200,
                        )
                        vision_provider = gr.Dropdown(
                            choices=["qwen3", "doubao"],
                            value="qwen3",
                            label="视觉模型"
                        )
                        vision_btn = gr.Button("👁️ 运行 Vision 调试", variant="secondary")
                    with gr.Column(scale=1):
                        vision_output = gr.Markdown(label="Vision 原始识别文本")
                        vision_img_url = gr.Textbox(label="上传后的公网 URL", interactive=False)

                vision_btn.click(
                    fn=vision_debug_logic,
                    inputs=[vision_input, vision_provider, auth_token_state],
                    outputs=[vision_output, vision_img_url],
                    show_progress=True,
                )

        gr.Markdown("""
        ---
        ### 🔧 技术架构
        - **前端**: Gradio (端口 7890)
        - **后端**: FastAPI (端口 8000)
        - **存储**: Supabase Storage（由后端写入，前端不直传）
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
    os.environ["GRADIO_API_INFO"] = "0"  # 禁用API信息获取以避免兼容性问题

    # 创建并启动 Demo
    demo = create_demo()
    demo.queue().launch(
        server_name="127.0.0.1",
        server_port=7890,
        show_error=True
    )
