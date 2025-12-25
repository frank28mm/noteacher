from __future__ import annotations

import argparse
import asyncio
import base64
import io
from pathlib import Path

from PIL import Image

from homework_agent.api.grade import perform_grading
from homework_agent.models.schemas import GradeRequest, ImageRef, Subject, VisionProvider


def _file_to_data_url(path: Path, *, max_side: int = 1600, jpeg_quality: int = 85) -> str:
    with Image.open(path) as img:
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_side:
            ratio = float(max_side) / float(max(w, h))
            nw = max(1, int(round(w * ratio)))
            nh = max(1, int(round(h * ratio)))
            img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
        data = buf.getvalue()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


async def _run(
    image_path: Path,
    subject: str,
    vision_provider: str,
    llm_provider: str | None,
    max_side: int,
    jpeg_quality: int,
) -> None:
    data_url = _file_to_data_url(image_path, max_side=max_side, jpeg_quality=jpeg_quality)
    req = GradeRequest(
        images=[ImageRef(base64=data_url)],
        subject=Subject(subject),
        vision_provider=VisionProvider(vision_provider),
        llm_provider=llm_provider,
        session_id="local_autonomous_demo",
    )
    provider_str = llm_provider or ("silicon" if req.vision_provider == VisionProvider.QWEN3 else "ark")
    result = await perform_grading(req, provider_str)
    payload = result.model_dump()
    print("=== GradeResponse ===")
    print(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run autonomous grade pipeline with a local image file.")
    parser.add_argument("--image", required=True, help="Path to local image file")
    parser.add_argument("--subject", default="math", choices=["math", "english"], help="Subject")
    parser.add_argument(
        "--vision-provider",
        default="doubao",
        choices=["doubao", "qwen3"],
        help="Vision provider",
    )
    parser.add_argument(
        "--llm-provider",
        default=None,
        choices=["ark", "silicon"],
        help="LLM provider override",
    )
    parser.add_argument("--max-side", type=int, default=1600, help="Max side length for local image")
    parser.add_argument("--jpeg-quality", type=int, default=85, help="JPEG quality for local image (1-100)")
    args = parser.parse_args()

    image_path = Path(args.image).expanduser().resolve()
    if not image_path.exists():
        raise SystemExit(f"Image not found: {image_path}")

    asyncio.run(
        _run(
            image_path,
            args.subject,
            args.vision_provider,
            args.llm_provider,
            args.max_side,
            args.jpeg_quality,
        )
    )


if __name__ == "__main__":
    main()
