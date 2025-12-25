from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class ErrorCode(str, Enum):
    # 4xx - Client errors
    INVALID_REQUEST = "E4000"
    INVALID_IMAGE_FORMAT = "E4001"
    QUESTION_NOT_FOUND = "E4004"
    UNAUTHORIZED = "E4010"
    FORBIDDEN = "E4030"
    VALIDATION_ERROR = "E4220"
    RATE_LIMITED = "E4290"

    # 5xx - Service errors
    SERVICE_ERROR = "E5000"
    VISION_TIMEOUT = "E5001"
    LLM_TIMEOUT = "E5002"
    URL_FETCH_FAILED = "E5003"
    REDIS_UNAVAILABLE = "E5004"
    OCR_DISABLED = "E5005"


class HomeworkAgentError(Exception):
    """Base error for homework agent."""


class VisionGradeAgentError(HomeworkAgentError):
    """Unified vision-grade agent error."""


class OpenCVProcessingError(VisionGradeAgentError):
    """OpenCV pipeline failure."""


class JSONRepairError(VisionGradeAgentError):
    """Structured output repair failure."""


class ToolExecutionError(VisionGradeAgentError):
    """Tool call execution failure."""


def error_code_for_http_status(status_code: int) -> ErrorCode:
    if status_code == 401:
        return ErrorCode.UNAUTHORIZED
    if status_code == 403:
        return ErrorCode.FORBIDDEN
    if status_code == 404:
        return ErrorCode.QUESTION_NOT_FOUND
    if status_code == 422:
        return ErrorCode.VALIDATION_ERROR
    if status_code == 429:
        return ErrorCode.RATE_LIMITED
    if 400 <= int(status_code) < 500:
        return ErrorCode.INVALID_REQUEST
    return ErrorCode.SERVICE_ERROR


def build_error_payload(
    *,
    code: ErrorCode,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    retry_after_ms: Optional[int] = None,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Canonical error shape for both HTTP JSON and SSE `event: error`.

    Backward compatibility:
    - keep `error` as the primary string message (older clients already parse this)
    - also include `message` as an alias for readability
    """
    payload: Dict[str, Any] = {"code": str(code), "error": str(message), "message": str(message)}
    if details is not None:
        payload["details"] = details
    if retry_after_ms is not None:
        payload["retry_after_ms"] = int(retry_after_ms)
    if request_id:
        payload["request_id"] = str(request_id)
    if session_id:
        payload["session_id"] = str(session_id)
    return payload
