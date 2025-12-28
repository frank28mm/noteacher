"""Vision client abstraction for silicon (qwen3) and ark (doubao) providers.

Provider whitelist matches docs/vision_providers.md:
- qwen3  -> SiliconFlow Qwen/Qwen3-VL-32B-Thinking (OpenAI-compatible)
- doubao -> Ark doubao-seed-1-6-vision-250815 (OpenAI SDK with input_image/input_text payload)

Notes:
- Only url/base64 inputs allowed; callers should validate upstream (schemas.ImageRef).
- Do not allow arbitrary base_url/model injection; use env-configured endpoints.
"""

import logging
import re
from functools import partial
from typing import List, Optional

import httpx
from openai import APIConnectionError, APITimeoutError, OpenAI
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from homework_agent.models.schemas import ImageRef, VisionProvider
from homework_agent.services.image_preprocessor import maybe_preprocess_for_vision
from homework_agent.utils.observability import trace_span
from homework_agent.utils.settings import get_settings

logger = logging.getLogger(__name__)


def _log_retry(op: str, retry_state):
    provider = retry_state.kwargs.get("provider", "unknown")
    model = None
    try:
        self_obj = retry_state.args[0]
        if provider == VisionProvider.QWEN3:
            model = getattr(self_obj, "silicon_model", None)
        elif provider == VisionProvider.DOUBAO:
            model = getattr(self_obj, "ark_model", None)
    except Exception:
        model = model or "unknown"
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "Retrying %s (provider=%s, model=%s), attempt=%s, exception=%s",
        op,
        provider,
        model,
        retry_state.attempt_number,
        exc,
    )


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
        # Ensure lower-level client timeout is never smaller than grade vision budget
        self.timeout_seconds = max(
            int(settings.vision_client_timeout_seconds),
            int(settings.grade_vision_timeout_seconds),
        )

    def _build_openai_client(self, base_url: str, api_key: str) -> OpenAI:
        return OpenAI(
            base_url=base_url, api_key=api_key, timeout=float(self.timeout_seconds)
        )

    def _strip_base64_prefix(self, data: str) -> str:
        return re.sub(r"^data:image/[^;]+;base64,", "", data, flags=re.IGNORECASE)

    def _is_public_url(self, url: str) -> bool:
        if not url:
            return False
        if re.match(r"^https?://", url) is None:
            return False
        if url.startswith("http://127.") or url.startswith("https://127."):
            return False
        if url.startswith("http://localhost") or url.startswith("https://localhost"):
            return False
        return True

    def _image_content_blocks(self, refs: List[ImageRef], provider: VisionProvider):
        blocks = []
        for ref in refs:
            if ref.url:
                if not self._is_public_url(str(ref.url)):
                    raise ValueError(
                        "Image URL must be public HTTP/HTTPS (no localhost/127)"
                    )
                preprocessed = maybe_preprocess_for_vision(str(ref.url))
                if preprocessed:
                    if provider == VisionProvider.DOUBAO:
                        blocks.append(
                            {"type": "input_image", "image_url": preprocessed}
                        )
                    else:
                        blocks.append(
                            {"type": "image_url", "image_url": {"url": preprocessed}}
                        )
                    continue
                if provider == VisionProvider.DOUBAO:
                    blocks.append({"type": "input_image", "image_url": str(ref.url)})
                else:
                    blocks.append(
                        {"type": "image_url", "image_url": {"url": str(ref.url)}}
                    )
            elif ref.base64:
                # Prefer URL uploads when possible, but allow Data URI fallback:
                # - Qwen3 (SiliconFlow) expects full Data URI in 'url' field.
                # - Doubao (Ark) accepts Data URI via `input_image.image_url` in practice (helps bypass provider-side URL fetch timeouts).
                # Do NOT strip prefix.

                # Approximate size check: 4/3 of base64 length
                est_bytes = int(len(ref.base64) * 0.75)
                if est_bytes > 20 * 1024 * 1024:
                    raise ValueError("Image size exceeds 20MB limit; use URL instead")
                if provider == VisionProvider.DOUBAO:
                    blocks.append({"type": "input_image", "image_url": ref.base64})
                else:
                    blocks.append(
                        {"type": "image_url", "image_url": {"url": ref.base64}}
                    )
        return blocks

    @trace_span("vision.analyze")
    @retry(
        retry=retry_if_exception_type(
            (
                APIConnectionError,
                APITimeoutError,
                httpx.ReadTimeout,
                httpx.ConnectTimeout,
            )
        ),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        before_sleep=partial(_log_retry, "vision.analyze"),
        reraise=True,
    )
    def analyze(
        self,
        images: List[ImageRef],
        prompt: Optional[str] = None,
        provider: VisionProvider = VisionProvider.DOUBAO,
    ) -> VisionResult:
        """Call selected vision provider and return text output + raw response.

        This is a minimal wrapper; downstream parsing (OCR/region) is up to caller.
        """

        if provider == VisionProvider.QWEN3:
            if not self.silicon_api_key:
                raise RuntimeError("SILICON_API_KEY not configured")
            client = self._build_openai_client(
                self.silicon_base_url, self.silicon_api_key
            )
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
