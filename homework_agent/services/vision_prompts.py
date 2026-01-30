from __future__ import annotations

from homework_agent.models.vision_facts import SceneType

BASE_VFE_PROMPT = """
You only do "visual fact extraction" from the image(s). Do NOT solve, do NOT prove, do NOT infer.

Output STRICT JSON only (no markdown, no extra text). Any uncertainty MUST be UNKNOWN and recorded in `unknowns`.

Required top-level fields (no extra keys):
{
  "scene_type": "...",
  "confidence": 0.0,
  "facts": {
    "lines": [],
    "points": [],
    "angles": [],
    "labels": [],
    "spatial": []
  },
  "hypotheses": [
    {"statement": "...", "confidence": 0.0, "evidence": ["..."]}
  ],
  "unknowns": [],
  "warnings": []
}

Rules:
- `scene_type` must be one of the allowed values provided by the caller. If unsure, use "unknown".
- `confidence` is 0..1. If handwriting/occlusion/low-res makes key items unclear, lower it.
- Facts MUST be descriptive only. Do NOT output reasoning words in facts: 同位角 / 内错角 / 平行 / 垂直 / 所以 / 因此 / 可得.
- Hypotheses are optional; if provided, each must include confidence and evidence that references facts.
- If the image does not contain a diagram (only text), put "diagram_missing" into `unknowns`.

Facts format:
- lines: array of objects, e.g. {"name": "AD", "direction": "horizontal", "relative": "above BC"}
- points: array of objects, e.g. {"name": "A", "relative": "left_of D; above B"}
- angles: array of objects:
  {"name": "∠2", "at": "D", "between": ["AD","DC"],
   "transversal_side": "left|right|unknown",
   "between_lines": "true|false|unknown"}
- labels/spatial: array of strings.
""".strip()


PLUGIN_PROMPTS = {
    # --- Math ---
    SceneType.MATH_GEOMETRY_2D: """
Special attention to 2D geometry:
1) Describe directions/relative positions of key segments (horizontal/vertical/slanted; above/below/left/right): AD, BC, AB, CD/DC if visible.
2) Describe point layout: A/B/C/D relative positions (e.g., "A is left of D and above B").
3) For each angle, fill:
   - transversal_side: left/right/unknown relative to the transversal line (e.g., DC).
   - between_lines: true if the angle lies between the two main lines (e.g., AD & BC), false if outside, unknown if unclear.
4) Use facts only; do NOT infer angle types (no 同位角/内错角 words in facts).
5) If angle labels/lines are unclear, set them to UNKNOWN and add a reason into `unknowns`/`warnings`.
""".strip(),
    SceneType.MATH_FUNCTION_GRAPH: """
Special attention to function graphs:
- Record axes labels, origin, tick marks, curve shape, labeled key points/intercepts (UNKNOWN if unreadable).
- Do not infer the function expression.
""".strip(),
    SceneType.MATH_CHART_OR_TABLE: """
Special attention to charts/tables:
- Record title, headers/axes, units, legend, visible numeric values (UNKNOWN if unreadable).
- Do not compute or compare; only record visible facts.
""".strip(),
    SceneType.MATH_SEQUENCE_OR_PATTERN: """
Special attention to patterns/sequences:
- Copy any visible example sequences/arrows/steps exactly as seen.
- Do not infer the pattern rule.
""".strip(),
    SceneType.MATH_GEOMETRY_3D: """
Special attention to 3D geometry:
- Distinguish solid vs dashed edges if visible; record face/edge labels as seen.
- Do not infer perpendicular/parallel between planes; only record explicit marks.
""".strip(),
    SceneType.MATH_WORD_WITH_DIAGRAM: """
Special attention to word problems with diagrams:
- Prefer diagram facts (layout, labels, arrows) and copy any given numbers/units.
- Do not solve the problem.
""".strip(),
    # --- English (Phase 1: stubs, still strict JSON) ---
    SceneType.EN_MAP_OR_ROUTE: """
English map/route (stub):
- Copy place names, arrows, directions (N/E/S/W), route labels as seen.
- If route/legend is unclear, set UNKNOWN and list in unknowns.
""".strip(),
    SceneType.EN_DIAGRAM_OR_FLOW: """
English diagram/flow (stub):
- Copy each node text and arrow connections (A -> B -> C) as seen.
- If arrows/labels unclear, set UNKNOWN and list in unknowns.
""".strip(),
    SceneType.EN_CHART_OR_TABLE: """
English chart/table (stub):
- Copy title, legend, axes/headers, units, visible values as seen.
- If any part unclear, set UNKNOWN and list in unknowns.
""".strip(),
    SceneType.EN_LABELLED_PICTURE: """
English labelled picture (stub):
- Copy each label text and what it points to (as seen).
- If label unreadable, set UNKNOWN and list in unknowns.
""".strip(),
}


STUB_SCENES = {
    SceneType.EN_MAP_OR_ROUTE,
    SceneType.EN_DIAGRAM_OR_FLOW,
    SceneType.EN_CHART_OR_TABLE,
    SceneType.EN_LABELLED_PICTURE,
}
