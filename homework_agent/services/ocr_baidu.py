"""
Baidu PaddleOCR-VL client (cloud OCR + layout analysis).

Implements:
- OAuth access_token via API Key/Secret
- Submit parsing task (URL-first; base64 fallback)
- Poll query endpoint until done/failed/timeout

This module is intentionally tolerant to response schema differences:
we keep raw response and provide best-effort extraction helpers.
"""

from __future__ import annotations

import base64
import logging
import time
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple

import httpx

from homework_agent.utils.settings import get_settings
from homework_agent.utils.observability import log_event, redact_url

logger = logging.getLogger(__name__)


@dataclass
class BaiduOCRTaskResult:
    task_id: str
    status: str
    raw: Dict[str, Any]


class BaiduPaddleOCRVLClient:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.baidu_ocr_api_key
        self.secret_key = settings.baidu_ocr_secret_key
        self.oauth_url = settings.baidu_ocr_oauth_url
        self.submit_url = settings.baidu_ocr_submit_url
        self.query_url = settings.baidu_ocr_query_url
        self.timeout_seconds = settings.baidu_ocr_timeout_seconds
        self.poll_interval_seconds = settings.baidu_ocr_poll_interval_seconds
        self.poll_max_seconds = settings.baidu_ocr_poll_max_seconds

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def is_configured(self) -> bool:
        return bool(self.api_key and self.secret_key)

    def _get_access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires_at - 30:
            return self._token
        if not self.api_key or not self.secret_key:
            raise RuntimeError("BAIDU_OCR_API_KEY/BAIDU_OCR_SECRET_KEY not configured")

        t0 = time.monotonic()
        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key,
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.get(self.oauth_url, params=params)
            resp.raise_for_status()
            data = resp.json()
        token = data.get("access_token")
        expires_in = float(data.get("expires_in") or 0)
        if not token:
            raise RuntimeError(f"Failed to get Baidu access_token: {data}")
        self._token = token
        self._token_expires_at = now + max(expires_in, 0)
        log_event(
            logger,
            "baidu_ocr_token_refreshed",
            oauth_host=urlparse(self.oauth_url).netloc,
            expires_in=int(expires_in) if expires_in else None,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
        return token

    def submit(self, *, image_url: Optional[str] = None, image_bytes: Optional[bytes] = None) -> str:
        """
        Submit an OCR/layout task. Prefer `image_url` (public https).
        Fallback to base64 if URL is rejected.
        Returns task_id (string).
        """
        token = self._get_access_token()
        url = f"{self.submit_url}?access_token={token}"
        endpoint_for_log = redact_url(url)

        # Per Baidu PaddleOCR-VL doc:
        # - Content-Type: application/x-www-form-urlencoded
        # - Body must include `file_name` (required) and one of `file_url` / `file_data`.
        def _infer_file_name() -> str:
            if image_url:
                try:
                    path = urlparse(image_url).path or ""
                    name = path.rsplit("/", 1)[-1].strip()
                    if name and "." in name:
                        return name[:128]
                except Exception:
                    pass
            # Fallback: Baidu requires a suffix; use jpg by default.
            return "document.jpg"

        file_name = _infer_file_name()

        def _post(payload: Dict[str, Any]) -> Dict[str, Any]:
            t0 = time.monotonic()
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(url, data=payload)
                resp.raise_for_status()
                data = resp.json()
            log_event(
                logger,
                "baidu_ocr_submit_http",
                endpoint=endpoint_for_log,
                mode="file_url" if "file_url" in payload else "file_data",
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                error_code=data.get("error_code"),
            )
            return data

        last: Dict[str, Any] = {}

        # 1) URL-first (most stable for our pipeline)
        if image_url:
            # Per Baidu PaddleOCR-VL doc: form body expects `file_url` (or `file_data`).
            try:
                log_event(
                    logger,
                    "baidu_ocr_submit_start",
                    endpoint=endpoint_for_log,
                    mode="file_url",
                    file_name=file_name,
                    image_url=redact_url(image_url),
                )
                last = _post({"file_url": image_url, "file_name": file_name})
                if last.get("error_code"):
                    raise RuntimeError(f"{last.get('error_code')}: {last.get('error_msg')}")
                task_id = (
                    last.get("task_id")
                    or last.get("taskId")
                    or (last.get("result") or {}).get("task_id")
                    or (last.get("data") or {}).get("task_id")
                )
                if task_id:
                    log_event(
                        logger,
                        "baidu_ocr_submit_ok",
                        endpoint=endpoint_for_log,
                        mode="file_url",
                        task_id=str(task_id),
                    )
                    return str(task_id)
            except Exception as e:
                log_event(
                    logger,
                    "baidu_ocr_submit_fallback",
                    endpoint=endpoint_for_log,
                    reason=f"{e.__class__.__name__}: {e}",
                    image_url=redact_url(image_url),
                )
                # fall through to base64 fallback
                pass

        # 2) Base64 fallback
        if image_bytes is None and image_url:
            try:
                # For downloading public images (e.g., Supabase public URL) we should not inherit
                # local proxy settings which may break localhost/public fetches on macOS.
                with httpx.Client(
                    timeout=self.timeout_seconds, follow_redirects=True, trust_env=False
                ) as client:
                    r = client.get(image_url)
                    r.raise_for_status()
                    image_bytes = r.content
            except Exception as e:
                raise RuntimeError(f"Baidu OCR submit failed (cannot download url for base64 fallback): {e}") from e

        if image_bytes is not None:
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            # Per Baidu PaddleOCR-VL doc: base64 should be passed as `file_data`.
            log_event(
                logger,
                "baidu_ocr_submit_start",
                endpoint=endpoint_for_log,
                mode="file_data",
                file_name=file_name,
                bytes_len=len(image_bytes),
            )
            last = _post({"file_data": b64, "file_name": file_name})
            if last.get("error_code"):
                raise RuntimeError(f"Baidu OCR submit failed: {last}")
            task_id = (
                last.get("task_id")
                or last.get("taskId")
                or (last.get("result") or {}).get("task_id")
                or (last.get("data") or {}).get("task_id")
            )
            if task_id:
                log_event(
                    logger,
                    "baidu_ocr_submit_ok",
                    endpoint=endpoint_for_log,
                    mode="file_data",
                    task_id=str(task_id),
                )
                return str(task_id)

        raise RuntimeError(f"Baidu OCR submit failed: {last}")

    def query(self, task_id: str) -> Dict[str, Any]:
        token = self._get_access_token()
        url = f"{self.query_url}?access_token={token}"
        endpoint_for_log = redact_url(url)
        payload = {"task_id": task_id}
        t0 = time.monotonic()
        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.post(url, data=payload)
            resp.raise_for_status()
            data = resp.json()
        log_event(
            logger,
            "baidu_ocr_query_http",
            endpoint=endpoint_for_log,
            task_id=str(task_id),
            status=str((data.get("status") or (data.get("result") or {}).get("status") or "")).strip() or None,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            error_code=data.get("error_code"),
        )
        return data

    def wait(self, task_id: str) -> BaiduOCRTaskResult:
        """
        Poll query endpoint until status indicates completion/failed or timeout.
        This is best-effort: schema varies; we look for common fields.
        """
        start = time.time()
        t0 = time.monotonic()
        polls = 0
        last: Dict[str, Any] = {}
        while True:
            last = self.query(task_id)
            polls += 1
            status = (
                (last.get("status") or "")
                or (last.get("result") or {}).get("status")
                or (last.get("data") or {}).get("status")
                or ""
            )
            status = str(status).lower()

            # Heuristics
            if any(k in status for k in ("done", "success", "finished", "complete", "completed")):
                log_event(
                    logger,
                    "baidu_ocr_wait_done",
                    task_id=str(task_id),
                    status="done",
                    polls=polls,
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                )
                return BaiduOCRTaskResult(task_id=str(task_id), status="done", raw=last)
            if any(k in status for k in ("fail", "failed", "error")):
                log_event(
                    logger,
                    "baidu_ocr_wait_done",
                    task_id=str(task_id),
                    status="failed",
                    polls=polls,
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                    error_code=last.get("error_code"),
                )
                return BaiduOCRTaskResult(task_id=str(task_id), status="failed", raw=last)

            if time.time() - start > self.poll_max_seconds:
                log_event(
                    logger,
                    "baidu_ocr_wait_done",
                    task_id=str(task_id),
                    status="timeout",
                    polls=polls,
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                )
                return BaiduOCRTaskResult(task_id=str(task_id), status="timeout", raw=last)

            time.sleep(self.poll_interval_seconds)

    @staticmethod
    def _fetch_parse_result_json(parse_result_url: str, *, timeout_seconds: float) -> Optional[Dict[str, Any]]:
        if not parse_result_url:
            return None
        try:
            # parse_result_url is a signed BOS URL with limited lifetime.
            t0 = time.monotonic()
            with httpx.Client(timeout=timeout_seconds, follow_redirects=True, trust_env=False) as client:
                resp = client.get(parse_result_url)
                resp.raise_for_status()
                data = resp.json()
            log_event(
                logger,
                "baidu_ocr_parse_result_fetched",
                parse_result_url=redact_url(parse_result_url),
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                pages=len(data.get("pages") or []) if isinstance(data, dict) else None,
            )
            return data if isinstance(data, dict) else None
        except Exception:
            log_event(
                logger,
                "baidu_ocr_parse_result_fetch_failed",
                level="warning",
                parse_result_url=redact_url(parse_result_url),
            )
            return None

    @staticmethod
    def extract_text_blocks(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Best-effort extraction of text blocks with bbox/polygon from Baidu response.
        This is intentionally permissive; caller should handle empty result.
        """
        # PaddleOCR-VL query response usually does NOT include blocks directly.
        # It returns `parse_result_url` / `markdown_url`, and the JSON at parse_result_url
        # contains per-page `layouts` with text + position.
        try:
            parse_url = None
            if isinstance(raw, dict):
                r = raw.get("result") if isinstance(raw.get("result"), dict) else None
                if isinstance(r, dict):
                    parse_url = r.get("parse_result_url") or r.get("parseResultUrl")
                parse_url = parse_url or raw.get("parse_result_url") or raw.get("parseResultUrl")
            if isinstance(parse_url, str) and parse_url.strip():
                parsed = BaiduPaddleOCRVLClient._fetch_parse_result_json(
                    parse_url.strip(), timeout_seconds=30.0
                )
                pages = (parsed or {}).get("pages") if isinstance(parsed, dict) else None
                if isinstance(pages, list) and pages:
                    blocks: List[Dict[str, Any]] = []
                    for p in pages:
                        if not isinstance(p, dict):
                            continue
                        layouts = p.get("layouts")
                        if not isinstance(layouts, list):
                            continue
                        for it in layouts:
                            if not isinstance(it, dict):
                                continue
                            text = it.get("text")
                            pos = it.get("position")
                            if not isinstance(text, str) or not text.strip():
                                continue
                            block: Dict[str, Any] = {"text": text.strip(), "type": it.get("type")}
                            # position is typically [x, y, w, h]
                            if isinstance(pos, (list, tuple)) and len(pos) == 4 and all(
                                isinstance(v, (int, float)) for v in pos
                            ):
                                x, y, w, h = float(pos[0]), float(pos[1]), float(pos[2]), float(pos[3])
                                block["location"] = {"left": x, "top": y, "width": w, "height": h}
                            blocks.append(block)
                    log_event(
                        logger,
                        "baidu_ocr_blocks_extracted",
                        mode="parse_result_url",
                        blocks=len(blocks),
                    )
                    return blocks
        except Exception:
            # Fall back to legacy extraction below.
            pass

        # Common nesting patterns
        candidates: List[Any] = []
        for path in (
            ("result", "blocks"),
            ("result", "data", "blocks"),
            ("data", "blocks"),
            ("blocks",),
            ("result", "pages"),
            ("result", "page_result"),
        ):
            cur: Any = raw
            ok = True
            for k in path:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    ok = False
                    break
            if ok and isinstance(cur, list):
                candidates = cur
                break
        blocks: List[Dict[str, Any]] = []
        for item in candidates or []:
            if isinstance(item, dict):
                blocks.append(item)
        log_event(logger, "baidu_ocr_blocks_extracted", mode="legacy", blocks=len(blocks))
        return blocks
