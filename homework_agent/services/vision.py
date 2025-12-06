"""Vision client abstraction for silicon (qwen3) and ark (doubao) providers.

Provider whitelist matches docs/vision_providers.md:
- qwen3  -> SiliconFlow Qwen/Qwen3-VL-32B-Thinking (OpenAI-compatible)
- doubao -> Ark doubao-seed-1-6-vision-250815 (OpenAI SDK with input_image/input_text payload)

Notes:
- Only url/base64 inputs allowed; callers should validate upstream (schemas.ImageRef).
- Do not allow arbitrary base_url/model injection; use env-configured endpoints.
"""

from typing import List, Optional

from pydantic import BaseModel
from openai import OpenAI

from homework_agent.models.schemas import ImageRef, VisionProvider
from homework_agent.utils.settings import get_settings


class VisionResult(BaseModel):
    text: str
    raw: dict


class VisionClient:
    def __init__(self):
        settings = get_settings()
        self.silicon_api_key = settings.silicon_api_key
        self.silicon_base_url = settings.silicon_base_url
        self.silicon_model = settings.silicon_vision_model

        self.ark_api_key = settings.ark_api_key
        self.ark_base_url = settings.ark_base_url
        self.ark_model = settings.ark_vision_model

    def _build_openai_client(self, base_url: str, api_key: str) -> OpenAI:
        return OpenAI(base_url=base_url, api_key=api_key)

    def _image_content_blocks(self, refs: List[ImageRef], provider: VisionProvider):
        blocks = []
        for ref in refs:
            if ref.url:
                if provider == VisionProvider.DOUBAO:
                    blocks.append({"type": "input_image", "image_url": ref.url})
                else:
                    blocks.append({"type": "image_url", "image_url": {"url": str(ref.url)}})
            elif ref.base64:
                # Some providers may not accept raw base64; callers should prefer URL uploads
                if provider == VisionProvider.DOUBAO:
                    blocks.append({"type": "input_image", "image_url": ref.base64})
                else:
                    blocks.append({"type": "image_url", "image_url": {"url": ref.base64}})
        return blocks

    def analyze(
        self,
        images: List[ImageRef],
        prompt: Optional[str] = None,
        provider: VisionProvider = VisionProvider.QWEN3,
    ) -> VisionResult:
        """Call selected vision provider and return text output + raw response.

        This is a minimal wrapper; downstream parsing (OCR/region) is up to caller.
        """

        if provider == VisionProvider.QWEN3:
            if not self.silicon_api_key:
                raise RuntimeError("SILICON_API_KEY not configured")
            client = self._build_openai_client(self.silicon_base_url, self.silicon_api_key)
            messages = [
                {
                    "role": "user",
                    "content": ([{"type": "text", "text": prompt}] if prompt else [])
                    + self._image_content_blocks(images, provider),
                }
            ]
            resp = client.chat.completions.create(
                model=self.silicon_model,
                messages=messages,
            )
            text = resp.choices[0].message.content if resp.choices else ""
            return VisionResult(text=text, raw=resp.to_dict())

        if provider == VisionProvider.DOUBAO:
            if not self.ark_api_key:
                raise RuntimeError("ARK_API_KEY not configured")
            client = self._build_openai_client(self.ark_base_url, self.ark_api_key)
            blocks = self._image_content_blocks(images, provider)
            content_blocks = []
            if prompt:
                content_blocks.append({"type": "input_text", "text": prompt})
            content_blocks.extend(blocks)
            resp = client.responses.create(
                model=self.ark_model,
                input=[{"role": "user", "content": content_blocks}],
            )
            # Ark responses.create returns a different schema; extract text cautiously
            text_parts = []
            for item in getattr(resp, "output", []) or []:
                for c in getattr(item, "content", []) or []:
                    if getattr(c, "type", None) == "output_text":
                        text_parts.append(getattr(c, "text", ""))
            return VisionResult(text="\n".join(text_parts), raw=resp.to_dict())

        raise ValueError(f"Unsupported vision provider: {provider}")
