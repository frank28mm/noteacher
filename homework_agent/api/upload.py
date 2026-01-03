import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Header, HTTPException, UploadFile, status, Request

from homework_agent.utils.supabase_client import get_storage_client
from homework_agent.utils.observability import get_request_id_from_headers, log_event
from homework_agent.utils.user_context import require_user_id
from homework_agent.utils.submission_store import create_submission_on_upload

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/uploads", status_code=status.HTTP_200_OK)
async def upload_files(
    request: Request,
    file: List[UploadFile] = File(...),
    session_id: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """
    Upload a file to Supabase Storage under a user-isolated path.

    Auth contract (Phase A):
    - If Authorization: Bearer <jwt> is provided, backend verifies it via Supabase Auth and uses jwt.sub as user_id.
    - Otherwise (AUTH_REQUIRED=0), dev fallback applies: X-User-Id or DEV_USER_ID.
    - Returns public URLs (bucket may be public during development).
    """
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    request_id = getattr(
        getattr(request, "state", None), "request_id", None
    ) or get_request_id_from_headers(request.headers)
    upload_id = f"upl_{uuid.uuid4().hex[:16]}"
    files_in = [f for f in (file or []) if f is not None]
    first = files_in[0] if files_in else None
    filename0 = (getattr(first, "filename", None) or "").strip() if first else ""
    content_type0 = (getattr(first, "content_type", None) or "").strip() if first else ""
    filename = filename0 or "upload"
    if len(files_in) > 1:
        filename = f"{filename} (+{len(files_in) - 1} files)"

    tmp_paths: List[str] = []
    total_size = 0
    urls: List[str] = []
    storage = get_storage_client()
    try:
        prefix = f"users/{user_id}/uploads/{upload_id}/"
        # Keep small and predictable: max 8 files per submission (PDF can still expand into pages).
        if len(files_in) > 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="too many files (max 8)",
            )

        for f in files_in:
            fname = (f.filename or "").strip() or "upload"
            suffix = Path(fname).suffix or ".bin"
            try:
                raw = await f.read()
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"read upload failed: {e}",
                )
            if not raw:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="empty file"
                )
            if len(raw) > 20 * 1024 * 1024:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="file exceeds 20MB"
                )
            total_size += int(len(raw))

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(raw)
                tmp.flush()
                tmp_paths.append(tmp.name)

            # For doubao compatibility, keep min_side conservative; heic/pdf conversion handled inside client.
            urls.extend(storage.upload_files(tmp.name, prefix=prefix, min_side=14))
    except HTTPException:
        raise
    except ValueError as e:
        # Catch image validation errors (e.g. too small) as 400
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        log_event(
            logger,
            "upload_failed",
            level="error",
            request_id=request_id,
            user_id=user_id,
            upload_id=upload_id,
            session_id=session_id,
            filename=filename,
            error_type=e.__class__.__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}",  # Expose error for debugging
        )
    finally:
        for tmp_path in tmp_paths:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception as e:
                    logger.debug(f"Failed to clean up temp file: {e}")

    # Best-effort: persist metadata to Supabase Postgres (requires table created via supabase/schema.sql).
    try:
        record = {
            "upload_id": upload_id,
            "user_id": user_id,
            "session_id": session_id,
            "filename": filename,
            "content_type": content_type0 or "multipart/mixed",
            "size_bytes": int(total_size),
            "page_image_urls": urls,
        }
        storage.client.table("user_uploads").insert(record).execute()
    except Exception as e:
        # Never fail upload response for optional DB insert during early dev.
        logger.debug(f"DB insert for upload failed (best-effort): {e}")

    # Best-effort: persist a durable Submission record (long-term "hard disk" source of truth).
    # We treat upload_id as submission_id (one upload == one submission).
    try:
        create_submission_on_upload(
            submission_id=upload_id,
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
            page_image_urls=urls,
            filename=filename,
            content_type=content_type0 or "multipart/mixed",
            size_bytes=int(total_size),
        )
    except Exception as e:
        logger.debug(f"create_submission_on_upload failed (best-effort): {e}")

    try:
        log_event(
            logger,
            "upload_done",
            request_id=request_id,
            user_id=user_id,
            upload_id=upload_id,
            session_id=session_id,
            pages=len(urls or []),
        )
    except Exception as e:
        logger.debug(f"upload_done log_event failed: {e}")

    return {
        "upload_id": upload_id,
        "user_id": user_id,
        "session_id": session_id,
        "page_image_urls": urls,
    }
