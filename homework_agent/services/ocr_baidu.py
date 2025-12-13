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
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple

import httpx

from homework_agent.utils.settings import get_settings

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
        return token

    def submit(self, *, image_url: Optional[str] = None, image_bytes: Optional[bytes] = None) -> str:
        """
        Submit an OCR/layout task. Prefer `image_url` (public https).
        Fallback to base64 if URL is rejected.
        Returns task_id (string).
        """
        token = self._get_access_token()
        url = f"{self.submit_url}?access_token={token}"

        def _post(payload: Dict[str, Any]) -> Dict[str, Any]:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(url, data=payload)
                resp.raise_for_status()
                return resp.json()

        last: Dict[str, Any] = {}

        # 1) URL-first (most stable for our pipeline)
        if image_url:
            for key in ("url", "image_url"):
                try:
                    last = _post({key: image_url})
                    # Baidu common error fields: error_code/error_msg
                    if last.get("error_code"):
                        raise RuntimeError(f"{last.get('error_code')}: {last.get('error_msg')}")
                    task_id = (
                        last.get("task_id")
                        or last.get("taskId")
                        or (last.get("result") or {}).get("task_id")
                        or (last.get("data") or {}).get("task_id")
                    )
                    if task_id:
                        return str(task_id)
                except Exception:
                    continue

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
            last = _post({"image": b64})
            if last.get("error_code"):
                raise RuntimeError(f"Baidu OCR submit failed: {last}")
            task_id = (
                last.get("task_id")
                or last.get("taskId")
                or (last.get("result") or {}).get("task_id")
                or (last.get("data") or {}).get("task_id")
            )
            if task_id:
                return str(task_id)

        raise RuntimeError(f"Baidu OCR submit failed: {last}")

    def query(self, task_id: str) -> Dict[str, Any]:
        token = self._get_access_token()
        url = f"{self.query_url}?access_token={token}"
        payload = {"task_id": task_id}
        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.post(url, data=payload)
            resp.raise_for_status()
            return resp.json()

    def wait(self, task_id: str) -> BaiduOCRTaskResult:
        """
        Poll query endpoint until status indicates completion/failed or timeout.
        This is best-effort: schema varies; we look for common fields.
        """
        start = time.time()
        last: Dict[str, Any] = {}
        while True:
            last = self.query(task_id)
            status = (
                (last.get("status") or "")
                or (last.get("result") or {}).get("status")
                or (last.get("data") or {}).get("status")
                or ""
            )
            status = str(status).lower()

            # Heuristics
            if any(k in status for k in ("done", "success", "finished", "complete", "completed")):
                return BaiduOCRTaskResult(task_id=str(task_id), status="done", raw=last)
            if any(k in status for k in ("fail", "failed", "error")):
                return BaiduOCRTaskResult(task_id=str(task_id), status="failed", raw=last)

            if time.time() - start > self.poll_max_seconds:
                return BaiduOCRTaskResult(task_id=str(task_id), status="timeout", raw=last)

            time.sleep(self.poll_interval_seconds)

    @staticmethod
    def extract_text_blocks(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Best-effort extraction of text blocks with bbox/polygon from Baidu response.
        This is intentionally permissive; caller should handle empty result.
        """
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
        return blocks
