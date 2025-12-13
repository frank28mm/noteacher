"""
QIndex worker process.

Run:
  source .venv/bin/activate
  export PYTHONPATH=/path/to/project
  python -m homework_agent.workers.qindex_worker

Requires:
  - REDIS_URL configured
  - redis python package installed
  - BAIDU_OCR_* configured if you want bbox/slice generation
"""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from typing import Any

from homework_agent.utils.settings import get_settings
from homework_agent.services.qindex_queue import (
    get_redis_client,
    queue_key,
    QIndexJob,
    store_qindex_result,
)

# Reuse the same builder used by the API, but run it out-of-process.
from homework_agent.api.routes import _build_question_index_for_pages  # noqa: E402

logger = logging.getLogger(__name__)


class _Stopper:
    stop = False


def _install_signal_handlers(stopper: _Stopper) -> None:
    def _handle(signum, frame):  # noqa: ARG001
        stopper.stop = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def main() -> int:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    client = get_redis_client()
    if client is None:
        logger.error("REDIS_URL not configured or redis unavailable; cannot start qindex worker.")
        return 2

    stopper = _Stopper()
    _install_signal_handlers(stopper)

    ttl_seconds = 24 * 3600
    try:
        # Keep TTL consistent with API session TTL where possible.
        ttl_seconds = int(settings.slice_ttl_seconds) if settings.slice_ttl_seconds else ttl_seconds
    except Exception:
        ttl_seconds = 24 * 3600

    qkey = queue_key()
    logger.info("QIndex worker started. queue=%s", qkey)

    while not stopper.stop:
        try:
            item = client.brpop(qkey, timeout=2)
            if not item:
                continue
            _, raw = item
            job = QIndexJob.from_json(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw))
            if not job.session_id or not job.page_urls:
                continue

            logger.info("Processing qindex job: session_id=%s pages=%d", job.session_id, len(job.page_urls))
            index: dict[str, Any] = _build_question_index_for_pages(job.page_urls)
            store_qindex_result(job.session_id, index, ttl_seconds=ttl_seconds)
            logger.info("Stored qindex: session_id=%s questions=%d", job.session_id, len(index.get("questions") or {}))

        except Exception as e:  # pragma: no cover
            logger.exception("QIndex worker error: %s", e)
            time.sleep(1)

    logger.info("QIndex worker stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

