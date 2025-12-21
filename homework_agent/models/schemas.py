from enum import Enum
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, AnyUrl, field_validator

# --- Basic Enums ---
class Subject(str, Enum):
    MATH = "math"
    ENGLISH = "english"


class Verdict(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    UNCERTAIN = "uncertain"


class Severity(str, Enum):
    CALCULATION = "calculation"
    CONCEPT = "concept"
    FORMAT = "format"
    UNKNOWN = "unknown"
    MEDIUM = "medium"
    MINOR = "minor"


class SimilarityMode(str, Enum):
    NORMAL = "normal"
    STRICT = "strict"


class VisionProvider(str, Enum):
    QWEN3 = "qwen3"
    DOUBAO = "doubao"


# --- Shared primitives ---
class BBoxNormalized(BaseModel):
    """Normalized [ymin, xmin, ymax, xmax] with origin top-left, y down, each in [0,1]."""

    coords: List[float] = Field(..., min_length=4, max_length=4)

    @field_validator("coords")
    @classmethod
    def _validate_coords(cls, v: List[float]):
        if any(x < 0 or x > 1 for x in v):
            raise ValueError("BBox values must be within [0,1]")
        ymin, xmin, ymax, xmax = v
        if ymax < ymin or xmax < xmin:
            raise ValueError("BBox ymax/xmax must be >= ymin/xmin")
        return v


class ImageRef(BaseModel):
    """Reference to an image either by URL or base64 string."""

    url: Optional[AnyUrl] = None
    base64: Optional[str] = Field(
        None, description="Data URL or raw base64-encoded image content"
    )

    @field_validator("base64")
    @classmethod
    def _strip_prefix(cls, v: Optional[str]):
        # Keep light validation: allow empty/None, otherwise non-empty string
        if v is not None and not v.strip():
            raise ValueError("base64 content cannot be empty")
        return v

    @field_validator("url")
    @classmethod
    def _ensure_one(cls, v, values):
        if v is None and not values.get("base64"):
            raise ValueError("Either url or base64 must be provided")
        return v

# --- Math Specific Structures ---
class MathStep(BaseModel):
    index: int = Field(..., description="Step number, 1-indexed")
    verdict: Verdict
    expected: Optional[str] = Field(None, description="Expected calculation/logic for this step")
    observed: Optional[str] = Field(None, description="Actual observed calculation/logic")
    hint: Optional[str] = Field(None, description="Socratic hint if this step is wrong")
    severity: Optional[Severity] = None
    bbox: Optional[BBoxNormalized] = Field(
        None,
        description="Optional normalized bbox for the step region, used for future highlighters",
    )

class GeometryElement(BaseModel):
    type: str = Field(..., description="line, angle, point, etc.")
    label: str = Field(..., description="Label like A, B, C, AB, etc.")
    status: Literal["correct", "missing", "misplaced"]
    description: Optional[str] = None

class GeometryInfo(BaseModel):
    description: str = Field(..., description="Natural language judgment, e.g., 'Auxiliary line BE is correct'")
    elements: List[GeometryElement] = Field(default_factory=list)

# --- Core Item Structures ---
class WrongItem(BaseModel):
    # Page & slice references
    page_image_url: Optional[AnyUrl] = Field(None, description="Full page image URL")
    slice_image_url: Optional[AnyUrl] = Field(None, description="Cropped review slice URL")
    page_bbox: Optional[BBoxNormalized] = Field(None, description="BBox on full page [0-1]")
    review_slice_bbox: Optional[BBoxNormalized] = Field(None, description="BBox of the review slice [0-1]")

    # Stable identifiers (optional, from upstream grader/DB)
    item_id: Optional[str] = Field(
        None, description="Stable wrong-item id from upstream storage (preferred over index)"
    )
    image_id: Optional[str] = Field(
        None, description="Optional image/page id to validate context binding"
    )

    # Core Feedback
    reason: str = Field(..., description="Explanation of why it is wrong")
    standard_answer: Optional[str] = Field(None, description="The correct answer (not always shown to student)")
    question_number: Optional[str] = Field(
        None,
        description="Original question number as on the paper (e.g., '27' or '15(2)')",
    )
    question_content: Optional[str] = Field(
        None, description="Short question stem/content (for UI display and routing)"
    )
    student_answer: Optional[str] = Field(
        None, description="Student answer (for UI display; chat will not directly reveal standard answers)"
    )
    warnings: List[str] = Field(default_factory=list, description="Per-item warnings (e.g., OCR ambiguity)")

    @field_validator("question_number", mode="before")
    @classmethod
    def _coerce_question_number(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        return s or None
    
    # Categorization
    knowledge_tags: List[str] = Field(default_factory=list, description="L2/L3 knowledge points, e.g., ['Math', 'Geometry', 'Triangle']")
    cross_subject_flag: Optional[bool] = Field(
        None, description="Flag if content seems cross-subject/mismatched"
    )
    
    # Subject Specific Details
    math_steps: Optional[List[MathStep]] = None
    geometry_check: Optional[GeometryInfo] = None
    # English scoring
    semantic_score: Optional[float] = Field(
        None, description="Semantic similarity score for English subjective questions"
    )
    similarity_mode: Optional[SimilarityMode] = Field(
        None, description="normal/strict, matches grading mode"
    )
    keywords_used: Optional[List[str]] = Field(
        None,
        description="Internal extracted keywords used in strict mode (for audit/debug)",
    )
    
    # Judgment basis - LLM's reasoning for the verdict
    judgment_basis: Optional[List[str]] = Field(
        None,
        description="判定依据：LLM 说明它是如何判断的（中文短句列表）",
    )

    
    # English specific could be added here if needed, but 'reason' usually suffices for MVP or 'semantic_score'

class GradeRequest(BaseModel):
    images: List[ImageRef] = Field(..., description="List of image references (url or base64)")
    upload_id: Optional[str] = Field(
        None,
        description="Optional upload id returned by /api/v1/uploads; when present, backend will resolve images from storage for this user",
    )
    subject: Subject
    batch_id: Optional[str] = Field(None, description="Client-side batch identifier")
    session_id: Optional[str] = Field(None, description="Session identifier for the batch")
    vision_provider: VisionProvider = Field(
        VisionProvider.DOUBAO,
        description="Vision provider selection, default doubao (URL preferred; may use data-url(base64) fallback); qwen3 is optional fallback (URL or data-url)",
    )
    llm_provider: Optional[str] = Field(
        None,
        description="LLM provider for grading: 'ark' (doubao), 'silicon' (qwen3). If None, uses config default.",
    )
    mode: Optional[SimilarityMode] = Field(
        None, description="normal/strict (applies to English grading)"
    )

class GradeResponse(BaseModel):
    wrong_items: List[WrongItem]
    summary: str = Field(..., description="Overall summary of the page/batch")
    subject: Subject
    job_id: Optional[str] = Field(None, description="Asynchronous job identifier")
    session_id: Optional[str] = Field(None, description="Session identifier for context continuation")
    status: Optional[Literal["processing", "done", "failed"]] = None
    total_items: Optional[int] = Field(None, description="Total questions detected")
    wrong_count: Optional[int] = Field(None, description="Number of wrong items")
    cross_subject_flag: Optional[bool] = Field(
        None, description="Flag if the batch seems cross-subject/mismatched"
    )
    warnings: List[str] = Field(default_factory=list)
    vision_raw_text: Optional[str] = Field(
        None, description="Vision API 原始识别文本，用于调试和验证"
    )
    visual_facts: Optional[Dict[str, Any]] = Field(
        None, description="视觉事实（按题号聚合的结构化事实 JSON）"
    )
    figure_present: Optional[Dict[str, str]] = Field(
        None, description="题目是否包含图像（按题号聚合，true/false/unknown）"
    )
    questions: Optional[List[Dict[str, Any]]] = Field(
        None, description="全题列表（含正确题目），每题包含 verdict、judgment_basis 等字段"
    )


# --- Chat/Socratic Structures ---
class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

class ChatRequest(BaseModel):
    history: List[Message]
    question: str
    subject: Subject
    session_id: Optional[str] = Field(None, description="Session identifier for context continuation")
    mode: Optional[SimilarityMode] = Field(None, description="normal/strict, aligns with grading mode")
    llm_model: Optional[str] = Field(
        None,
        description="Optional LLM reasoning model override for chat (debug/demo only).",
    )
    # Context from previous grading
    context_item_ids: Optional[List[str | int]] = Field(
        None,
        description=(
            "Optional wrong item identifiers for targeted tutoring; supports index or item_id"
        ),
    )


class ChatResponse(BaseModel):
    messages: List[Message]
    session_id: Optional[str] = None
    retry_after_ms: Optional[int] = Field(
        None, description="Backoff hint for clients when rate limiting applies"
    )
    cross_subject_flag: Optional[bool] = None
    focus_image_urls: Optional[List[str]] = Field(
        default=None,
        description="Optional image URLs for the current focused question (e.g. qindex slice URLs) for UI rendering.",
    )
    focus_image_source: Optional[str] = Field(
        default=None,
        description="Source hint for focus_image_urls: slice_figure/slice_question/page/unknown.",
    )
    question_candidates: Optional[List[str]] = Field(
        default=None,
        description="Optional candidate question numbers/titles for UI fallback selection.",
    )
