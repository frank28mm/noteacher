import asyncio
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile, status

from homework_agent.utils.observability import get_request_id_from_headers, log_event
from homework_agent.utils.profile_context import require_profile_id
from homework_agent.utils.settings import get_settings
from homework_agent.utils.submission_store import create_submission_on_upload
from homework_agent.utils.supabase_client import get_storage_client
from homework_agent.utils.user_context import require_user_id

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/uploads", status_code=status.HTTP_200_OK)
async def upload_files(
    request: Request,
    file: List[UploadFile] = File(...),
    session_id: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_profile_id: Optional[str] = Header(None, alias="X-Profile-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """
    Upload a file to Supabase Storage under a user-isolated path.

    Auth contract (Phase A):
    - If Authorization: Bearer <jwt> is provided, backend verifies it via Supabase Auth and uses jwt.sub as user_id.
    - Otherwise (AUTH_REQUIRED=0), dev fallback applies: X-User-Id or DEV_USER_ID.
    - Returns public URLs (bucket may be public during development).
    """
    user_id = await asyncio.to_thread(
        require_user_id, authorization=authorization, x_user_id=x_user_id
    )
    profile_id = await asyncio.to_thread(
        require_profile_id, user_id=user_id, x_profile_id=x_profile_id
    )
    request_id = getattr(
        getattr(request, "state", None), "request_id", None
    ) or get_request_id_from_headers(request.headers)
    upload_id = f"upl_{uuid.uuid4().hex[:16]}"
    files_in = [f for f in (file or []) if f is not None]
    first = files_in[0] if files_in else None
    filename0 = (getattr(first, "filename", None) or "").strip() if first else ""
    content_type0 = (
        (getattr(first, "content_type", None) or "").strip() if first else ""
    )
    filename = filename0 or "upload"
    if len(files_in) > 1:
        filename = f"{filename} (+{len(files_in) - 1} files)"

    tmp_paths: List[str] = []
    total_size = 0
    urls: List[str] = []
    storage = get_storage_client()
    try:
        prefix = f"users/{user_id}/uploads/{upload_id}/"
        # Keep small and predictable: max 4 images per submission.
        if len(files_in) > 4:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="too many files (max 4)",
            )

        settings = get_settings()
        max_bytes = int(getattr(settings, "max_upload_image_bytes", 5 * 1024 * 1024))

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
            if len(raw) > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"file exceeds {max_bytes} bytes",
                )
            total_size += int(len(raw))

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(raw)
                tmp.flush()
                tmp_paths.append(tmp.name)

            # For doubao compatibility, keep min_side conservative; heic/pdf conversion handled inside client.
            urls.extend(
                await asyncio.to_thread(
                    storage.upload_files,
                    tmp.name,
                    prefix=prefix,
                    min_side=14,
                )
            )
    except HTTPException:
        raise
    except ValueError as e:
        # Catch image validation errors (e.g. too small) as 400
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
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
        settings = get_settings()
        env = str(getattr(settings, "app_env", "dev") or "dev").strip().lower()
        detail = "Internal server error"
        if env not in {"prod", "production"}:
            detail = f"Internal server error: {str(e)}"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )
    finally:
        for tmp_path in tmp_paths:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception as e:
                    logger.debug(f"Failed to clean up temp file: {e}")

    # Best-effort: persist a durable Submission record (long-term "hard disk" source of truth).
    # We treat upload_id as submission_id (one upload == one submission).
    try:
        await asyncio.to_thread(
            create_submission_on_upload,
            submission_id=upload_id,
            user_id=user_id,
            profile_id=profile_id,
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
