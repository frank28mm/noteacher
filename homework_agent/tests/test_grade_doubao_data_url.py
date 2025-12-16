import pytest

from homework_agent.api.grade import validate_images_payload
from homework_agent.models.schemas import VisionProvider


def test_validate_images_payload_allows_doubao_data_url_base64():
    validate_images_payload(
        images=[{"base64": "data:image/jpeg;base64,AAA="}],
        vision_provider=VisionProvider.DOUBAO,
    )


def test_validate_images_payload_rejects_doubao_raw_base64():
    with pytest.raises(Exception):
        validate_images_payload(
            images=[{"base64": "AAA="}],
            vision_provider=VisionProvider.DOUBAO,
        )
