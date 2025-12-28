import json

import pytest

from homework_agent.models.schemas import Subject, VisionProvider
from homework_agent.models.vision_facts import SceneType, VisualFacts
from homework_agent.services import vision_facts as vf


def test_build_prompt_includes_geometry_plugin():
    prompt = vf._build_prompt(scene_type=SceneType.MATH_GEOMETRY_2D)
    assert "Special attention to 2D geometry" in prompt
    assert "STRICT JSON" in prompt or "Output STRICT JSON" in prompt


def test_extract_visual_facts_repairs_wrapped_json(monkeypatch):
    # Avoid network
    monkeypatch.setattr(vf, "_download_as_data_uri", lambda url: None)

    class DummyRes:
        def __init__(self, text: str):
            self.text = text

    class DummyVisionClient:
        def analyze(self, images, prompt=None, provider=VisionProvider.DOUBAO):
            assert images  # built from URLs
            payload = {
                "scene_type": "math.geometry_2d",
                "confidence": 0.9,
                "facts": {
                    "lines": [
                        {
                            "name": "AD",
                            "direction": "horizontal",
                            "relative": "above BC",
                        }
                    ],
                    "points": [],
                    "angles": [],
                    "labels": [],
                    "spatial": [],
                },
                "hypotheses": [],
                "unknowns": [],
                "warnings": [],
            }
            return DummyRes(
                "some header\n" + json.dumps(payload, ensure_ascii=False) + "\ntrailer"
            )

    monkeypatch.setattr(vf, "VisionClient", DummyVisionClient)

    facts, repaired, raw = vf.extract_visual_facts(
        image_urls=["https://example.com/a.jpg"],
        scene_type=SceneType.MATH_GEOMETRY_2D,
        provider=VisionProvider.DOUBAO,
    )
    assert repaired is True
    assert raw
    assert isinstance(facts, VisualFacts)
    assert facts.scene_type == SceneType.MATH_GEOMETRY_2D
    assert facts.confidence == pytest.approx(0.9)


def test_extract_visual_facts_stub_scene_adds_warning(monkeypatch):
    monkeypatch.setattr(vf, "_download_as_data_uri", lambda url: None)

    class DummyRes:
        def __init__(self, text: str):
            self.text = text

    class DummyVisionClient:
        def analyze(self, images, prompt=None, provider=VisionProvider.DOUBAO):
            payload = {
                "scene_type": "en.map_or_route",
                "confidence": 0.0,
                "facts": {
                    "lines": [],
                    "points": [],
                    "angles": [],
                    "labels": [],
                    "spatial": [],
                },
                "hypotheses": [],
                "unknowns": ["route is unclear"],
                "warnings": [],
            }
            return DummyRes(json.dumps(payload))

    monkeypatch.setattr(vf, "VisionClient", DummyVisionClient)

    facts, repaired, _raw = vf.extract_visual_facts(
        image_urls=["https://example.com/a.jpg"],
        scene_type=SceneType.EN_MAP_OR_ROUTE,
        provider=VisionProvider.DOUBAO,
    )
    assert repaired is False
    assert facts is not None
    assert "plugin_is_stub" in (facts.warnings or [])
    assert facts.confidence == pytest.approx(0.5)


def test_extract_visual_facts_coerces_object_arrays(monkeypatch):
    """
    Some providers may return arrays of objects (e.g. {"id": "...", "description": "..."}).
    We must coerce them into string lists so VFE doesn't fail-closed on schema mismatch.
    """
    monkeypatch.setattr(vf, "_download_as_data_uri", lambda url: None)

    class DummyRes:
        def __init__(self, text: str):
            self.text = text

    class DummyVisionClient:
        def analyze(self, images, prompt=None, provider=VisionProvider.DOUBAO):
            payload = {
                "scene_type": "math.geometry_2d",
                "confidence": 0.8,
                "facts": {
                    "lines": [
                        {
                            "name": "AD",
                            "direction": "horizontal",
                            "relative": "above BC",
                        },
                        {
                            "name": "BC",
                            "direction": "horizontal",
                            "relative": "below AD",
                        },
                    ],
                    "points": [{"name": "A", "relative": "left of D"}],
                    "angles": [
                        {
                            "name": "∠2",
                            "at": "D",
                            "between": "AD",
                            "transversal_side": "left",
                        }
                    ],
                    "labels": ["A", "B", "C", "D"],
                    "spatial": [],
                },
                "hypotheses": [],
                "unknowns": [],
                "warnings": [],
            }
            return DummyRes(json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(vf, "VisionClient", DummyVisionClient)

    facts, repaired, raw = vf.extract_visual_facts(
        image_urls=["https://example.com/a.jpg"],
        scene_type=SceneType.MATH_GEOMETRY_2D,
        provider=VisionProvider.DOUBAO,
    )
    assert repaired is False
    assert raw
    assert isinstance(facts, VisualFacts)
    assert facts.facts.lines and facts.facts.lines[0].name == "AD"
    assert facts.facts.points and facts.facts.points[0].name == "A"
    assert facts.facts.angles and facts.facts.angles[0].name == "∠2"


def test_gate_visual_facts_low_confidence():
    facts = VisualFacts(
        scene_type=SceneType.MATH_GEOMETRY_2D, confidence=0.2, unknowns=["∠2 UNKNOWN"]
    )
    gate = vf.gate_visual_facts(
        facts=facts,
        scene_type=SceneType.MATH_GEOMETRY_2D,
        visual_risk=True,
        user_text="讲讲第9题",
        image_source="slice_figure",
        repaired_json=False,
    )
    assert gate.passed is False
    assert gate.trigger == "low_confidence"


def test_gate_visual_facts_critical_unknown_hits_angle_2():
    facts = VisualFacts(
        scene_type=SceneType.MATH_GEOMETRY_2D,
        confidence=0.9,
        facts={"angles": [{"name": "∠2"}]},
        unknowns=["∠2 位置为 UNKNOWN"],
    )
    gate = vf.gate_visual_facts(
        facts=facts,
        scene_type=SceneType.MATH_GEOMETRY_2D,
        visual_risk=True,
        user_text="∠2 在AD上方还是下方？看图回答",
        image_source="slice_figure",
        repaired_json=False,
    )
    assert gate.passed is False
    assert gate.trigger == "critical_unknown"
    assert "ANGLE_2" in (gate.critical_unknowns_hit or [])


def test_gate_visual_facts_passes_when_confident_and_no_unknowns():
    facts = VisualFacts(
        scene_type=SceneType.MATH_GEOMETRY_2D,
        confidence=0.95,
        facts={
            "lines": [
                {"name": "AD", "direction": "horizontal", "relative": "above BC"}
            ],
            "angles": [
                {"name": "∠2", "transversal_side": "left", "between_lines": True},
                {"name": "∠BCD", "transversal_side": "right", "between_lines": True},
            ],
        },
        unknowns=[],
        warnings=[],
    )
    gate = vf.gate_visual_facts(
        facts=facts,
        scene_type=SceneType.MATH_GEOMETRY_2D,
        visual_risk=True,
        user_text="讲讲第9题",
        image_source="slice_figure",
        repaired_json=False,
    )
    assert gate.passed is True


def test_detect_scene_type_math_geometry_keywords():
    st = vf.detect_scene_type(
        subject=Subject.MATH,
        user_text="看图判断同位角还是内错角",
        question_content="如图，证明AD∥BC",
        visual_risk=True,
        has_figure_slice=True,
    )
    assert st == SceneType.MATH_GEOMETRY_2D
