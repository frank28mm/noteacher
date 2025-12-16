import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Header, HTTPException, UploadFile, status

from homework_agent.utils.supabase_client import get_storage_client
from homework_agent.utils.observability import log_event
from homework_agent.utils.user_context import get_user_id
from homework_agent.utils.submission_store import create_submission_on_upload

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/uploads", status_code=status.HTTP_200_OK)
async def upload_files(
    file: UploadFile = File(...),
    session_id: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> Dict[str, Any]:
    """
    Upload a file to Supabase Storage under a user-isolated path.

    Current dev contract:
    - Caller may supply X-User-Id header; otherwise DEV_USER_ID is used.
    - Returns public URLs (bucket may be public during development).
    """
    user_id = get_user_id(x_user_id)
    upload_id = f"upl_{uuid.uuid4().hex[:16]}"
    filename = (file.filename or "").strip() or "upload"

    # Keep suffix for mime sniffing (pdf/heic/jpg/png etc.)
    suffix = Path(filename).suffix
    if not suffix:
        suffix = ".bin"

    try:
        raw = await file.read()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"read upload failed: {e}")

    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file exceeds 20MB")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            tmp.flush()
            tmp_path = tmp.name

        storage = get_storage_client()
        prefix = f"users/{user_id}/uploads/{upload_id}/"
        # For doubao compatibility, keep min_side conservative; heic/pdf conversion handled inside client.
        urls: List[str] = storage.upload_files(tmp_path, prefix=prefix, min_side=14)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    # Best-effort: persist metadata to Supabase Postgres (requires table created via supabase/schema.sql).
    try:
        record = {
            "upload_id": upload_id,
            "user_id": user_id,
            "session_id": session_id,
            "filename": filename,
            "content_type": file.content_type,
            "size_bytes": len(raw),
            "page_image_urls": urls,
        }
        storage.client.table("user_uploads").insert(record).execute()
    except Exception:
        # Never fail upload response for optional DB insert during early dev.
        pass

    # Best-effort: persist a durable Submission record (long-term "hard disk" source of truth).
    # We treat upload_id as submission_id (one upload == one submission).
    try:
        create_submission_on_upload(
            submission_id=upload_id,
            user_id=user_id,
            session_id=session_id,
            page_image_urls=urls,
            filename=filename,
            content_type=file.content_type,
            size_bytes=len(raw),
        )
    except Exception:
        pass

    try:
        log_event(
            logger,
            "upload_done",
            user_id=user_id,
            upload_id=upload_id,
            session_id=session_id,
            pages=len(urls or []),
        )
    except Exception:
        pass

    return {
        "upload_id": upload_id,
        "user_id": user_id,
        "session_id": session_id,
        "page_image_urls": urls,
    }
