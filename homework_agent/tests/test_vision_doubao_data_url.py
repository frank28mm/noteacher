from homework_agent.models.schemas import ImageRef, VisionProvider
from homework_agent.services.vision import VisionClient


def test_doubao_allows_data_url_base64_blocks():
    client = VisionClient()
    blocks = client._image_content_blocks(  # type: ignore[attr-defined]
        [ImageRef(base64="data:image/jpeg;base64,AAA=")],
        provider=VisionProvider.DOUBAO,
    )
    assert blocks and blocks[0]["type"] == "input_image"
