from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class SceneType(str, Enum):
    # Math
    MATH_GEOMETRY_2D = "math.geometry_2d"
    MATH_GEOMETRY_3D = "math.geometry_3d"
    MATH_CHART_OR_TABLE = "math.chart_or_table"
    MATH_FUNCTION_GRAPH = "math.function_graph"
    MATH_SEQUENCE_OR_PATTERN = "math.sequence_or_pattern"
    MATH_WORD_WITH_DIAGRAM = "math.word_with_diagram"
    # English
    EN_MAP_OR_ROUTE = "en.map_or_route"
    EN_DIAGRAM_OR_FLOW = "en.diagram_or_flow"
    EN_CHART_OR_TABLE = "en.chart_or_table"
    EN_LABELLED_PICTURE = "en.labelled_picture"
    # Default
    UNKNOWN = "unknown"


class LineFact(BaseModel):
    name: Optional[str] = None
    direction: Optional[str] = None
    relative: Optional[str] = None


class PointFact(BaseModel):
    name: Optional[str] = None
    relative: Optional[str] = None


class AngleFact(BaseModel):
    name: Optional[str] = None
    at: Optional[str] = None
    between: List[str] = Field(default_factory=list)
    transversal_side: str = Field(default="unknown")
    between_lines: str = Field(default="unknown")

    @field_validator("transversal_side", mode="before")
    @classmethod
    def _normalize_transversal_side(cls, value: Optional[str]) -> str:
        s = str(value or "").strip().lower()
        if s in {"left", "right", "unknown"}:
            return s
        return "unknown"

    @field_validator("between_lines", mode="before")
    @classmethod
    def _normalize_between_lines(cls, value: Optional[object]) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        s = str(value or "").strip().lower()
        if s in {"true", "false", "unknown"}:
            return s
        return "unknown"


class VisualHypothesis(BaseModel):
    statement: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    evidence: List[str] = Field(default_factory=list)


class VisualFactBundle(BaseModel):
    lines: List[LineFact] = Field(default_factory=list)
    points: List[PointFact] = Field(default_factory=list)
    angles: List[AngleFact] = Field(default_factory=list)
    labels: List[str] = Field(default_factory=list)
    spatial: List[str] = Field(default_factory=list)


class VisualFacts(BaseModel):
    """
    Vision Fact Extraction (VFE) output: structured facts + optional hypotheses.
    Facts must be descriptive only (no geometric reasoning words).
    """

    scene_type: SceneType = SceneType.UNKNOWN
    figure_present: str = Field(default="unknown")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    facts: VisualFactBundle = Field(default_factory=VisualFactBundle)
    hypotheses: List[VisualHypothesis] = Field(default_factory=list)
    unknowns: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    @field_validator("figure_present", mode="before")
    @classmethod
    def _normalize_figure_present(cls, value: Optional[object]) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        s = str(value or "").strip().lower()
        if s in {"true", "false", "unknown"}:
            return s
        return "unknown"


class GateResult(BaseModel):
    """Fail-closed decision for whether VisualFacts can be used for reasoning."""

    passed: bool
    trigger: Optional[str] = None
    critical_unknowns_hit: List[str] = Field(default_factory=list)
    user_facing_message: Optional[str] = None
    repaired_json: bool = False
