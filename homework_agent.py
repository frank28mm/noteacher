import asyncio
import os
import json
import re
import cv2
import numpy as np
from typing import Any, List, Tuple
from PIL import Image
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pillow_heif = None
from dotenv import load_dotenv
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    tool,
    create_sdk_mcp_server,
    AssistantMessage,
    TextBlock,
    ToolUseBlock
)

load_dotenv()

# --- Tools ---

def _imread_unicode(path: str):
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is not None:
        return img
    # Fallback to PIL (handles HEIC when pillow_heif is installed)
    try:
        pil_img = Image.open(path)
        pil_img = pil_img.convert("RGB")
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def _imwrite_unicode(path: str, image, params=None):
    ext = os.path.splitext(path)[1] or ".jpg"
    success, buf = cv2.imencode(ext, image, params or [])
    if not success:
        return False
    buf.tofile(path)
    return True


def _split_image_into_tiles(image_path: str, max_tile_edge: int = 1200) -> List[str]:
    """
    Split a large image into tiles with max edge length max_tile_edge to keep payloads small
    without downscaling the original resolution. Returns absolute tile paths.
    """
    abs_path = os.path.abspath(image_path)
    img = _imread_unicode(abs_path)
    if img is None:
        raise ValueError(f"Could not read image at {abs_path}")

    h, w = img.shape[:2]
    tiles: List[str] = []
    # Determine grid counts
    cols = max(1, int(np.ceil(w / max_tile_edge)))
    rows = max(1, int(np.ceil(h / max_tile_edge)))
    tile_w = int(np.ceil(w / cols))
    tile_h = int(np.ceil(h / rows))

    base, _ = os.path.splitext(abs_path)
    for r in range(rows):
        for c in range(cols):
            x0 = c * tile_w
            y0 = r * tile_h
            x1 = min(w, x0 + tile_w)
            y1 = min(h, y0 + tile_h)
            tile = img[y0:y1, x0:x1]
            tile_path = f"{base}_tile_r{r}_c{c}.jpg"
            # Save with high quality to avoid visible compression while keeping size manageable.
            _imwrite_unicode(tile_path, tile, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            tiles.append(tile_path)
    return tiles


def _extract_json(text: str) -> Tuple[bool, Any]:
    """
    Try to extract the first JSON object from a text block.
    Returns (success, parsed_obj or None).
    """
    # Look for fenced code blocks first
    fenced = re.findall(r"```json\\s*(\\{[\\s\\S]*?\\})\\s*```", text)
    candidates = fenced if fenced else [text]
    for candidate in candidates:
        try:
            return True, json.loads(candidate)
        except Exception:
            continue
    return False, None


@tool("crop_and_zoom", "Crop a specific area of the image and zoom in. Returns the absolute path to the new image.", {"image_path": str, "x": int, "y": int, "width": int, "height": int, "zoom_factor": float})
async def crop_and_zoom(args: dict[str, Any]) -> dict[str, Any]:
    try:
        image_path = os.path.abspath(args["image_path"])
        x = int(args["x"])
        y = int(args["y"])
        w = int(args["width"])
        h = int(args["height"])
        zoom = float(args.get("zoom_factor", 2.0))

        img = _imread_unicode(image_path)
        if img is None:
            return {"content": [{"type": "text", "text": f"Error: Could not read image at {image_path}"}], "is_error": True}

        img_h, img_w = img.shape[:2]
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = max(1, min(w, img_w - x))
        h = max(1, min(h, img_h - y))

        cropped = img[y:y+h, x:x+w]
        new_w = int(w * zoom)
        new_h = int(h * zoom)
        zoomed = cv2.resize(cropped, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

        base, ext = os.path.splitext(image_path)
        output_path = f"{base}_crop_{x}_{y}{ext}"
        _imwrite_unicode(output_path, zoomed)

        return {
            "content": [{
                "type": "text",
                "text": f"Image cropped and zoomed. Saved to {output_path}."
            }]
        }
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "is_error": True
        }

@tool("enhance_image", "Enhance image quality (denoise, threshold). Returns absolute path to new image.", {"image_path": str})
async def enhance_image(args: dict[str, Any]) -> dict[str, Any]:
    try:
        image_path = os.path.abspath(args["image_path"])
        img = _imread_unicode(image_path)
        if img is None:
            return {"content": [{"type": "text", "text": f"Error: Could not read image at {image_path}"}], "is_error": True}

        denoised = cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)
        gray = cv2.cvtColor(denoised, cv2.COLOR_BGR2GRAY)
        adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)

        base, ext = os.path.splitext(image_path)
        output_path = f"{base}_enhanced{ext}"
        _imwrite_unicode(output_path, adaptive)

        return {
            "content": [{
                "type": "text",
                "text": f"Image enhanced. Saved to {output_path}."
            }]
        }
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "is_error": True
        }

# --- Agent ---

class HomeworkAgent:
    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self.model_name = os.getenv("MODEL_NAME", "claude-3-5-sonnet-20241022")
        self.mcp_server = create_sdk_mcp_server(
            name="image_tools",
            version="1.0.0",
            tools=[crop_and_zoom, enhance_image]
        )

    def prepare_tiles(self, image_paths: List[str], max_tile_edge: int = 1200) -> List[str]:
        """
        Split each input image into tiles (no downscale) to keep payloads under buffer limits.
        """
        tile_paths: List[str] = []
        for path in image_paths:
            try:
                tiles = _split_image_into_tiles(path, max_tile_edge=max_tile_edge)
                tile_paths.extend(tiles)
            except Exception as exc:
                print(f"[warn] tiling failed for {path}: {exc}")
                # Fall back to original if tiling fails
                tile_paths.append(os.path.abspath(path))
        return tile_paths

    async def check_homework(self, image_paths: List[str]):
        # Convert to absolute paths
        abs_paths = [os.path.abspath(p) for p in image_paths]
        print(f"Checking homework (original): {abs_paths}")

        # Tile images to avoid compression while keeping payload small
        tile_paths = self.prepare_tiles(abs_paths, max_tile_edge=1200)
        print(f"Checking homework (tiles): {tile_paths}")

        async def message_stream():
            instructions = (
                "You are an expert math homework checker. "
                "There are 16 math questions on this page. "
                "Process EVERY provided tile image with the Read tool; do not rely on memory. "
                "If any tile is unclear, you may use crop_and_zoom or enhance_image on that tile path. "
                "Think step-by-step: first survey all tiles, then solve each problem, then verify answers. "
                "Output strictly JSON with keys: subject, problems (list of id 1..16, question, student_answer, correct_answer, "
                "is_correct, correction), and summary. Provide brief reasoning for corrections inside the JSON values only."
                f" Tile image paths to process (no downscaling, just crops): {tile_paths}"
            )
            yield {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": instructions
                }
            }

        options = ClaudeAgentOptions(
            model=self.model_name,
            mcp_servers={"img_tools": self.mcp_server},
            allowed_tools=[
                "Read",
                "mcp__img_tools__crop_and_zoom",
                "mcp__img_tools__enhance_image"
            ],
            max_turns=8
        )

        def save_json_if_any(text: str):
            ok, obj = _extract_json(text)
            if not ok or obj is None:
                return
            os.makedirs("output", exist_ok=True)
            base = os.path.splitext(os.path.basename(abs_paths[0]))[0] if abs_paths else "result"
            out_path = os.path.join("output", f"{base}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
            print(f"[saved] JSON -> {out_path}")

        async with ClaudeSDKClient(options=options) as client:
            await client.query(message_stream())
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"Agent: {block.text}")
                            save_json_if_any(block.text)

if __name__ == "__main__":
    # For testing
    pass
