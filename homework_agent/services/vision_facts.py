from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from homework_agent.models.schemas import ImageRef, Subject, VisionProvider
from homework_agent.models.vision_facts import GateResult, SceneType, VisualFacts
from homework_agent.services.vision import VisionClient
from homework_agent.services.vision_prompts import BASE_VFE_PROMPT, PLUGIN_PROMPTS, STUB_SCENES
from homework_agent.utils.url_image_helpers import _download_as_data_uri

logger = logging.getLogger(__name__)


VFE_CONF_MIN = 0.50
VFE_CONF_GEOMETRY = 0.50
VFE_CONF_STRONG = 0.85


@dataclass(frozen=True)
class VFEImageSelection:
    image_urls: List[str]
    image_source: str  # slice_figure/slice_question/page/none


def _coerce_list_str(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        s = v.strip()
        return [s] if s else []
    if isinstance(v, list):
        out: List[str] = []
        for it in v:
            if it is None:
                continue
            if isinstance(it, str):
                s = it.strip()
                if s:
                    out.append(s)
                continue
            if isinstance(it, dict):
                parts: List[str] = []
                for key in ("name", "text", "label", "position", "relative", "description"):
                    val = it.get(key)
                    if val:
                        parts.append(str(val).strip())
                s = " ".join([p for p in parts if p])
                if s:
                    out.append(s)
                    continue
            s = str(it).strip()
            if s:
                out.append(s)
        return list(dict.fromkeys(out))
    s = str(v).strip()
    return [s] if s else []


def _coerce_line_fact(v: Any) -> Dict[str, Any]:
    if isinstance(v, dict):
        return v
    s = str(v or "").strip()
    return {"name": s} if s else {}


def _coerce_point_fact(v: Any) -> Dict[str, Any]:
    if isinstance(v, dict):
        return v
    s = str(v or "").strip()
    return {"name": s} if s else {}


def _coerce_angle_fact(v: Any) -> Dict[str, Any]:
    if isinstance(v, dict):
        out = dict(v)
    else:
        s = str(v or "").strip()
        out = {"name": s} if s else {}
    if "between" in out and isinstance(out.get("between"), str):
        out["between"] = [str(out["between"]).strip()]
    return out


def _coerce_hypothesis(v: Any) -> Dict[str, Any]:
    if isinstance(v, dict):
        out = dict(v)
    else:
        s = str(v or "").strip()
        out = {"statement": s} if s else {}
    out["evidence"] = _coerce_list_str(out.get("evidence"))
    if "confidence" not in out:
        out["confidence"] = 0.0
    return out


def _coerce_list_dict(v: Any, coerce_fn) -> List[Dict[str, Any]]:
    if v is None:
        return []
    if isinstance(v, list):
        out: List[Dict[str, Any]] = []
        for it in v:
            d = coerce_fn(it)
            if d:
                out.append(d)
        return out
    d = coerce_fn(v)
    return [d] if d else []


def _looks_like_visual_facts(obj: Dict[str, Any]) -> bool:
    if not isinstance(obj, dict):
        return False
    return any(k in obj for k in ("facts", "scene_type", "confidence"))


def _normalize_visual_facts_obj(obj: Any, scene_type: SceneType) -> Optional[VisualFacts]:
    if not isinstance(obj, dict):
        return None

    # Normalize into the new schema while remaining tolerant to legacy outputs.
    try:
        obj = dict(obj)
        facts_obj = obj.get("facts") if isinstance(obj.get("facts"), dict) else {}

        if "facts" not in obj:
            for k in ("lines", "points", "angles", "labels"):
                if k in obj:
                    facts_obj[k] = obj.get(k)
            if "spatial_facts" in obj and "spatial" not in facts_obj:
                facts_obj["spatial"] = obj.get("spatial_facts")
            if "spatial" in obj and "spatial" not in facts_obj:
                facts_obj["spatial"] = obj.get("spatial")

        if "spatial_facts" in facts_obj and "spatial" not in facts_obj:
            facts_obj["spatial"] = facts_obj.get("spatial_facts")

        facts_obj["lines"] = _coerce_list_dict(facts_obj.get("lines"), _coerce_line_fact)
        facts_obj["points"] = _coerce_list_dict(facts_obj.get("points"), _coerce_point_fact)
        facts_obj["angles"] = _coerce_list_dict(facts_obj.get("angles"), _coerce_angle_fact)
        facts_obj["labels"] = _coerce_list_str(facts_obj.get("labels"))
        facts_obj["spatial"] = _coerce_list_str(facts_obj.get("spatial"))

        if "figure_present" not in obj and "figure_present" in facts_obj:
            obj["figure_present"] = facts_obj.get("figure_present")
            facts_obj.pop("figure_present", None)

        obj["facts"] = facts_obj
        obj["hypotheses"] = _coerce_list_dict(obj.get("hypotheses"), _coerce_hypothesis)
        obj["unknowns"] = _coerce_list_str(obj.get("unknowns"))
        obj["warnings"] = _coerce_list_str(obj.get("warnings"))
    except Exception:
        return None

    try:
        facts = VisualFacts.model_validate(obj)
    except Exception:
        return None

    try:
        if facts.scene_type == SceneType.UNKNOWN and scene_type != SceneType.UNKNOWN:
            facts.scene_type = scene_type
    except Exception:
        pass

    if scene_type in STUB_SCENES:
        facts.warnings = list(dict.fromkeys((facts.warnings or []) + ["plugin_is_stub"]))
        if facts.confidence <= 0.0:
            facts.confidence = 0.5

    return facts


def detect_scene_type(
    *,
    subject: Subject,
    user_text: str,
    question_content: str,
    visual_risk: bool,
    has_figure_slice: bool,
) -> SceneType:
    """
    Heuristic scene routing (lightweight, no extra model call).
    Default: unknown.
    """
    msg = f"{user_text or ''} {question_content or ''}".strip()
    msg = msg.replace("（", "(").replace("）", ")")

    if subject == Subject.MATH:
        if any(k in msg for k in ("∠", "角", "平行", "垂直", "几何", "同位角", "内错角", "同旁内角", "位置关系", "如图")):
            return SceneType.MATH_GEOMETRY_2D
        if any(k in msg for k in ("函数图像", "二次函数", "坐标系", "坐标轴", "抛物线")):
            return SceneType.MATH_FUNCTION_GRAPH
        if any(k in msg for k in ("表格", "统计图", "折线图", "柱状图", "扇形图")):
            return SceneType.MATH_CHART_OR_TABLE
        if any(k in msg for k in ("规律", "数列", "图形拼接", "箭头", "→")):
            return SceneType.MATH_SEQUENCE_OR_PATTERN
        if any(k in msg for k in ("立体", "长方体", "正方体", "圆锥", "圆柱", "棱", "面")):
            return SceneType.MATH_GEOMETRY_3D

        if visual_risk or has_figure_slice:
            return SceneType.MATH_WORD_WITH_DIAGRAM
        return SceneType.UNKNOWN

    # English
    if any(k.lower() in msg.lower() for k in ("map", "route", "north", "south", "east", "west")) or any(
        k in msg for k in ("地图", "路线", "方向", "路标", "N", "S", "E", "W")
    ):
        return SceneType.EN_MAP_OR_ROUTE
    if any(k.lower() in msg.lower() for k in ("flow", "diagram", "process")) or any(
        k in msg for k in ("流程图", "示意图", "箭头", "步骤")
    ):
        return SceneType.EN_DIAGRAM_OR_FLOW
    if any(k.lower() in msg.lower() for k in ("chart", "table", "graph")) or any(
        k in msg for k in ("表格", "统计图", "柱状图", "折线图")
    ):
        return SceneType.EN_CHART_OR_TABLE
    if any(k.lower() in msg.lower() for k in ("label", "picture")) or any(k in msg for k in ("看图", "图片", "标注")):
        return SceneType.EN_LABELLED_PICTURE

    return SceneType.UNKNOWN


def select_vfe_images(*, focus_question: Dict[str, Any]) -> VFEImageSelection:
    """
    Deterministic image selection:
    1) figure slice
    2) question slice
    3) page image
    """

    def _pick_from_pages(pages: Any) -> Tuple[Optional[str], Optional[str]]:
        if not isinstance(pages, list):
            return None, None
        for p in pages:
            if not isinstance(p, dict):
                continue
            regions = p.get("regions")
            if isinstance(regions, list):
                for r in regions:
                    if not isinstance(r, dict):
                        continue
                    if (r.get("kind") or "").lower() == "figure" and r.get("slice_image_url"):
                        return str(r.get("slice_image_url")), "slice_figure"
            su = p.get("slice_image_urls") or p.get("slice_image_url")
            if isinstance(su, str) and su.strip():
                return str(su), "slice_question"
            if isinstance(su, list):
                for u in su:
                    if u:
                        return str(u), "slice_question"
            if isinstance(regions, list):
                for r in regions:
                    if isinstance(r, dict) and r.get("slice_image_url"):
                        return str(r.get("slice_image_url")), "slice_question"
        return None, None

    refs = focus_question.get("image_refs")
    if isinstance(refs, dict):
        url, src = _pick_from_pages(refs.get("pages"))
        if url:
            return VFEImageSelection(image_urls=[url], image_source=src or "unknown")
    url, src = _pick_from_pages(focus_question.get("pages"))
    if url:
        return VFEImageSelection(image_urls=[url], image_source=src or "unknown")

    page_urls = focus_question.get("page_image_urls")
    if isinstance(page_urls, list) and page_urls:
        return VFEImageSelection(image_urls=[str(page_urls[0])], image_source="page")
    page_url = focus_question.get("page_image_url")
    if page_url:
        return VFEImageSelection(image_urls=[str(page_url)], image_source="page")

    return VFEImageSelection(image_urls=[], image_source="none")


def _extract_first_json_object(text: str) -> Optional[str]:
    if not text:
        return None
    s = str(text)
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


_REASONING_BANNED = (
    "同位角",
    "内错角",
    "所以",
    "因此",
    "可得",
    "故",
    "结论",
    "证明",
    "最短",
    "应该是",
)


def _facts_look_like_reasoning(facts: VisualFacts) -> bool:
    blobs: List[str] = []

    def add(*parts: Optional[str]) -> None:
        chunk = " ".join([str(p).strip() for p in parts if p is not None and str(p).strip()])
        if chunk:
            blobs.append(chunk)

    try:
        bundle = facts.facts
        for line in bundle.lines or []:
            add(getattr(line, "name", None), getattr(line, "direction", None), getattr(line, "relative", None))
        for point in bundle.points or []:
            add(getattr(point, "name", None), getattr(point, "relative", None))
        for ang in bundle.angles or []:
            add(
                getattr(ang, "name", None),
                getattr(ang, "at", None),
                " ".join(getattr(ang, "between", None) or []),
                getattr(ang, "transversal_side", None),
                getattr(ang, "between_lines", None),
            )
        for label in bundle.labels or []:
            add(label)
        for sp in bundle.spatial or []:
            add(sp)
    except Exception:
        pass

    joined = " ".join(blobs)
    return any(k in joined for k in _REASONING_BANNED)


def _normalize_tokens(text: str) -> List[str]:
    s = (text or "").strip()
    if not s:
        return []
    s = s.replace("（", "(").replace("）", ")")
    out: List[str] = []

    # diagram missing
    if "diagram_missing" in s or ("未见" in s and "图" in s):
        out.append("DIAGRAM_MISSING")

    # angles
    if re.search(r"(∠|角)\s*1", s) or re.search(r"\bangle\s*1\b", s, flags=re.I):
        out.append("ANGLE_1")
    if re.search(r"(∠|角)\s*2", s) or re.search(r"\bangle\s*2\b", s, flags=re.I):
        out.append("ANGLE_2")
    if "BCD" in s or "∠BCD" in s or re.search(r"\bangle\s*bcd\b", s, flags=re.I):
        out.append("ANGLE_BCD")

    # segments / lines
    for seg in ("AD", "BC", "AB", "CD", "DC"):
        if seg in s:
            out.append("CD" if seg == "DC" else seg)

    # positional words (used to detect "position dispute" questions)
    if any(k in s for k in ("上方", "上面", "上侧")):
        out.append("ABOVE")
    if any(k in s for k in ("下方", "下面", "下侧")):
        out.append("BELOW")
    if any(k in s for k in ("左侧", "左边")):
        out.append("LEFT")
    if any(k in s for k in ("右侧", "右边")):
        out.append("RIGHT")

    return list(dict.fromkeys(out))


def _angle_token_for_name(name: Optional[str]) -> Optional[str]:
    s = str(name or "").strip()
    if not s:
        return None
    if "BCD" in s or "∠BCD" in s or re.search(r"\bangle\s*bcd\b", s, flags=re.I):
        return "ANGLE_BCD"
    if re.search(r"(∠|角)\s*1", s) or re.search(r"\bangle\s*1\b", s, flags=re.I):
        return "ANGLE_1"
    if re.search(r"(∠|角)\s*2", s) or re.search(r"\bangle\s*2\b", s, flags=re.I):
        return "ANGLE_2"
    return None


def _confidence_threshold(scene_type: SceneType) -> float:
    if scene_type in (SceneType.MATH_GEOMETRY_2D, SceneType.MATH_GEOMETRY_3D):
        return VFE_CONF_GEOMETRY
    return VFE_CONF_MIN


def _critical_unknown_tokens(*, scene_type: SceneType, user_text: str) -> List[str]:
    """
    Return a list of canonical tokens that are critical for the current user query under a scene type.
    """
    msg = (user_text or "").strip()
    tokens = set(_normalize_tokens(msg))

    if scene_type == SceneType.MATH_GEOMETRY_2D:
        asking_position = any(k in msg for k in ("位置关系", "上方", "下方", "左侧", "右侧", "像F", "像Z"))
        asking_angle_type = any(k in msg for k in ("同位角", "内错角", "同旁内角"))
        asking_parallel = any(k in msg for k in ("平行", "垂直", "截线", "被截线"))
        if asking_position or asking_angle_type or asking_parallel:
            # If user asks any position dispute, angle tokens become critical.
            if "ANGLE_1" in tokens or "ANGLE_2" in tokens or "ANGLE_BCD" in tokens:
                pass
            else:
                # If user didn't name them, still treat the common ones as critical for geometry disputes.
                tokens.update({"ANGLE_1", "ANGLE_2", "ANGLE_BCD"})
        if asking_parallel:
            tokens.update({"AD", "BC", "AB", "CD"})
        return sorted(tokens)

    if scene_type in (SceneType.MATH_CHART_OR_TABLE, SceneType.EN_CHART_OR_TABLE):
        # For charts, we mainly require headers/units/legend when interpreting.
        if any(k in msg for k in ("读图", "表格", "统计图", "比较", "变化", "趋势", "increase", "decrease")):
            return ["CHART_HEADERS_OR_UNITS"]
        return []

    if scene_type == SceneType.MATH_FUNCTION_GRAPH:
        if any(k in msg for k in ("函数", "图像", "坐标", "顶点", "交点")):
            return ["AXES_OR_KEY_POINTS"]
        return []

    if scene_type == SceneType.EN_MAP_OR_ROUTE:
        if any(k in msg.lower() for k in ("route", "direction", "north", "south")) or any(
            k in msg for k in ("路线", "方向")
        ):
            return ["ROUTE_OR_DIRECTIONS"]
        return []

    if scene_type == SceneType.UNKNOWN:
        if any(k in msg for k in ("看图", "如图", "位置关系", "图")):
            return ["DIAGRAM_MISSING"]
        return []

    return []


def gate_visual_facts(
    *,
    facts: VisualFacts,
    scene_type: SceneType,
    visual_risk: bool,
    user_text: str,
    image_source: str,
    repaired_json: bool,
) -> GateResult:
    # Hard validation: VFE must not reason.
    if _facts_look_like_reasoning(facts):
        return GateResult(
            passed=False,
            trigger="facts_contains_reasoning",
            critical_unknowns_hit=[],
            user_facing_message="我目前无法可靠提取这题的客观图像事实，因此不能判断位置关系；请提供更清晰的局部截图或稍后重试。",
            repaired_json=repaired_json,
        )

    # Stub scenes are treated as low-confidence until fully implemented.
    is_stub = bool(scene_type in STUB_SCENES or "plugin_is_stub" in (facts.warnings or []))
    if is_stub and visual_risk:
        return GateResult(
            passed=False,
            trigger="stub_plugin",
            critical_unknowns_hit=[],
            user_facing_message="这题需要稳定的看图能力才能判断，但当前该类图题的事实抽取插件仍在完善中；请你发更清晰的局部截图或稍后再试。",
            repaired_json=repaired_json,
        )

    # Confidence threshold
    threshold = _confidence_threshold(scene_type)
    if float(getattr(facts, "confidence", 0.0) or 0.0) < float(threshold):
        # For unknown scenes, allow pass only when confidence is strong.
        if scene_type == SceneType.UNKNOWN and float(getattr(facts, "confidence", 0.0) or 0.0) >= float(VFE_CONF_STRONG):
            return GateResult(passed=True, repaired_json=repaired_json)
        return GateResult(
            passed=False,
            trigger="low_confidence",
            critical_unknowns_hit=[],
            user_facing_message="我看不清图中关键标注（清晰度/手写遮挡），所以不能可靠判断位置关系；请发更清晰的局部截图或稍后再试。",
            repaired_json=repaired_json,
        )

    # figure missing in risky case
    if visual_risk and scene_type != SceneType.UNKNOWN and image_source not in {"slice_figure", "slice_question"}:
        return GateResult(
            passed=False,
            trigger="figure_missing",
            critical_unknowns_hit=[],
            user_facing_message="这题属于图形题，但我目前没有拿到图形区域的切片（figure），所以无法确认关键位置关系；请等待切片生成或补发该题图形局部。",
            repaired_json=repaired_json,
        )

    # Critical unknown hits
    critical = _critical_unknown_tokens(scene_type=scene_type, user_text=user_text)
    unknown_tokens: List[str] = []
    for u in (facts.unknowns or []):
        unknown_tokens.extend(_normalize_tokens(str(u)))
    unknown_tokens = list(dict.fromkeys(unknown_tokens))

    hits = set(critical).intersection(set(unknown_tokens))

    # Geometry: require per-angle positional fields when the user asks position/angle relations.
    if scene_type == SceneType.MATH_GEOMETRY_2D and visual_risk:
        try:
            angle_map: Dict[str, Any] = {}
            for ang in (facts.facts.angles or []):
                token = _angle_token_for_name(getattr(ang, "name", None))
                if token and token not in angle_map:
                    angle_map[token] = ang
            if not (facts.facts.angles or []):
                hits.add("ANGLES_MISSING")
            for token in critical:
                if not token.startswith("ANGLE_"):
                    continue
                ang = angle_map.get(token)
                if not ang:
                    hits.add(token)
                    continue
                if getattr(ang, "transversal_side", "unknown") == "unknown":
                    hits.add(token)
                if getattr(ang, "between_lines", "unknown") == "unknown":
                    hits.add(token)
        except Exception:
            hits.add("ANGLES_MISSING")

    if hits:
        return GateResult(
            passed=False,
            trigger="critical_unknown",
            critical_unknowns_hit=sorted(hits),
            user_facing_message="我目前无法从图中确认关键位置/标注（UNKNOWN），所以不能直接判断；请发更清晰的局部截图或稍后再试。",
            repaired_json=repaired_json,
        )

    return GateResult(passed=True, repaired_json=repaired_json)


def _build_prompt(*, scene_type: SceneType) -> str:
    plugin = PLUGIN_PROMPTS.get(scene_type) or ""
    allowed = ", ".join([st.value for st in SceneType])
    return (
        BASE_VFE_PROMPT
        + "\n\n"
        + f"Allowed scene_type values: {allowed}\n"
        + f"Target scene_type (preferred): {scene_type.value}\n"
        + ("\n\n" + plugin if plugin else "")
    ).strip()


def extract_visual_facts(
    *,
    image_urls: Sequence[str],
    scene_type: SceneType,
    provider: VisionProvider = VisionProvider.DOUBAO,
) -> Tuple[Optional[VisualFacts], bool, Optional[str]]:
    """
    Returns: (facts|None, repaired_json_used, raw_text|None)
    """
    cleaned = [str(u).strip() for u in (image_urls or []) if str(u).strip()]
    if not cleaned:
        return None, False, None

    prompt = _build_prompt(scene_type=scene_type)
    images: List[ImageRef] = []
    for u in cleaned:
        # Prefer local download+data-uri for stability (provider-side URL fetch can be flaky).
        data_uri = _download_as_data_uri(u)
        if data_uri:
            images.append(ImageRef(base64=data_uri))
        else:
            images.append(ImageRef(url=u))

    client = VisionClient()
    res = client.analyze(images=images, prompt=prompt, provider=provider)
    raw = (getattr(res, "text", None) or "").strip()
    if not raw:
        return None, False, raw

    repaired = False
    try:
        obj = json.loads(raw)
    except Exception:
        block = _extract_first_json_object(raw)
        if not block:
            return None, False, raw
        repaired = True
        try:
            obj = json.loads(block)
        except Exception:
            return None, repaired, raw

    facts = _normalize_visual_facts_obj(obj, scene_type)
    if not facts:
        return None, repaired, raw
    return facts, repaired, raw


def parse_visual_facts_map(
    raw_json: str,
    *,
    scene_type: SceneType = SceneType.UNKNOWN,
) -> Tuple[Dict[str, Any], bool]:
    """
    Parse a per-question visual_facts JSON payload into a map.
    Returns: (facts_map, repaired_json_used)
    """
    if not raw_json:
        return {}, False

    repaired = False
    try:
        obj = json.loads(raw_json)
    except Exception:
        block = _extract_first_json_object(raw_json)
        if not block:
            return {}, False
        repaired = True
        try:
            obj = json.loads(block)
        except Exception:
            return {}, repaired

    if not isinstance(obj, dict):
        return {}, repaired

    # Accept either {"questions": {...}} or {"visual_facts": {...}} or a single VisualFacts object.
    if _looks_like_visual_facts(obj):
        facts = _normalize_visual_facts_obj(obj, scene_type)
        return ({"_global": facts.model_dump()} if facts else {}), repaired

    qmap = obj.get("questions") if isinstance(obj.get("questions"), dict) else None
    if qmap is None and isinstance(obj.get("visual_facts"), dict):
        qmap = obj.get("visual_facts")
    if qmap is None:
        qmap = obj
    if not isinstance(qmap, dict):
        return {}, repaired

    out: Dict[str, Any] = {}
    for qn, payload in qmap.items():
        facts = _normalize_visual_facts_obj(payload, scene_type)
        if facts:
            out[str(qn)] = facts.model_dump()
    return out, repaired
