from types import SimpleNamespace

from homework_agent.services import autonomous_tools as tools
from homework_agent.core.layout_index import QuestionLayout


def test_vision_roi_detect_not_configured(monkeypatch):
    class _Locator:
        def is_configured(self):
            return False

    monkeypatch.setattr(tools, "SiliconFlowQIndexLocator", _Locator)
    result = tools.vision_roi_detect(image="http://example.com/img.jpg", prefix="p/")
    assert result["status"] == "error"
    assert result["message"] == "locator_not_configured"


def test_vision_roi_detect_success(monkeypatch):
    class _Locator:
        def is_configured(self):
            return True

        def locate(self, *, image_url, only_question_numbers=None):
            return SimpleNamespace(
                questions=[
                    {
                        "question_number": "1",
                        "regions": [
                            {"kind": "figure", "bbox_norm_xyxy": [0.1, 0.1, 0.2, 0.2]},
                        ],
                    }
                ]
            )

    def _fake_crop_and_upload_slices(
        *, page_image_url, layouts, only_question_numbers, prefix
    ):
        layout = QuestionLayout(
            question_number="1",
            bboxes_norm=[[0.1, 0.1, 0.2, 0.2]],
            slice_image_urls=["https://example.com/fig.jpg"],
            warnings=[],
        )
        return {"1": layout}

    monkeypatch.setattr(tools, "SiliconFlowQIndexLocator", _Locator)
    monkeypatch.setattr(tools, "crop_and_upload_slices", _fake_crop_and_upload_slices)

    result = tools.vision_roi_detect(image="http://example.com/img.jpg", prefix="p/")
    assert result["status"] == "ok"
    assert result["regions"]
    assert result["regions"][0]["kind"] == "figure"
    assert result["regions"][0]["slice_url"] == "https://example.com/fig.jpg"
