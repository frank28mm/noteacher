import hashlib
import json
import uuid
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, status, Request, Header, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import AsyncIterator, Dict, Any, Optional, List, Tuple, Iterable
import re

from homework_agent.models.schemas import (
    GradeRequest, GradeResponse, ChatRequest, ChatResponse,
    VisionProvider, Message, Subject, SimilarityMode
)
from homework_agent.services.vision import VisionClient
from homework_agent.services.llm import LLMClient, MathGradingResult, EnglishGradingResult
from homework_agent.utils.settings import get_settings
from homework_agent.utils.cache import get_cache_store, BaseCache

logger = logging.getLogger(__name__)

router = APIRouter()

# 缓存：可配置 Redis，默认进程内存
cache_store: BaseCache = get_cache_store()

# 常量
MAX_SOCRATIC_TURNS = 5
SESSION_TTL_HOURS = 24
IDP_TTL_HOURS = 24


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    return cache_store.get(f"sess:{session_id}")


def save_session(session_id: str, data: Dict[str, Any]) -> None:
    cache_store.set(f"sess:{session_id}", data, ttl_seconds=SESSION_TTL_HOURS * 3600)


def delete_session(session_id: str) -> None:
    cache_store.delete(f"sess:{session_id}")


def save_mistakes(session_id: str, wrong_items: List[Dict[str, Any]]) -> None:
    """缓存错题列表供辅导上下文使用，仅限当前批次，会话 TTL 同步。"""
    # 为每个 wrong_item 补充本地索引与稳定 item_id，便于后续检索
    enriched = []
    for idx, item in enumerate(wrong_items):
        enriched_item = dict(item)
        item_id = enriched_item.get("item_id") or enriched_item.get("id")
        if not item_id:
            item_id = f"item-{idx}"
        enriched_item["item_id"] = str(item_id)
        enriched_item.setdefault("id", idx)
        enriched.append(enriched_item)
    cache_store.set(
        f"mistakes:{session_id}",
        {"wrong_items": enriched, "ts": datetime.now().isoformat()},
        ttl_seconds=SESSION_TTL_HOURS * 3600,
    )


def get_mistakes(session_id: str) -> Optional[List[Dict[str, Any]]]:
    data = cache_store.get(f"mistakes:{session_id}")
    if not data:
        return None
    return data.get("wrong_items")


def normalize_context_ids(raw_ids: Iterable[Any]) -> List[str | int]:
    """Normalize context ids: strip strings, cast digit strings to int, drop empties."""
    normalized: List[str | int] = []
    for cid in raw_ids:
        if cid is None:
            continue
        if isinstance(cid, str):
            trimmed = cid.strip()
            if not trimmed:
                continue
            if trimmed.isdigit():
                try:
                    normalized.append(int(trimmed))
                    continue
                except ValueError:
                    pass
            normalized.append(trimmed)
        elif isinstance(cid, int):
            normalized.append(cid)
    return normalized


def resolve_context_items(
    context_ids: List[str | int], mistakes: Optional[List[Dict[str, Any]]]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Select wrong_items by index or item_id/id. Returns (selected, missing_list).
    """
    if not mistakes:
        return [], [str(cid) for cid in context_ids]

    selected: List[Dict[str, Any]] = []
    missing: List[str] = []
    by_item_id = {str(m.get("item_id")): m for m in mistakes if m.get("item_id")}
    by_local_id = {str(m.get("id")): m for m in mistakes if m.get("id") is not None}

    for cid in context_ids:
        if isinstance(cid, int):
            if 0 <= cid < len(mistakes):
                selected.append(mistakes[cid])
            else:
                missing.append(str(cid))
        else:
            item = by_item_id.get(str(cid)) or by_local_id.get(str(cid))
            if item:
                selected.append(item)
            else:
                missing.append(str(cid))
    return selected, missing


def assistant_tail(history: List[Dict[str, Any]], max_messages: int = 3) -> List[Dict[str, Any]]:
    """Return last N assistant messages in chronological order for replay."""
    assistants = [m for m in history if m.get("role") == "assistant"]
    if not assistants:
        return []
    tail = assistants[-max_messages:]
    return tail


def validate_vision_provider(provider: VisionProvider) -> VisionProvider:
    """验证vision_provider是否在白名单中"""
    allowed_providers = [VisionProvider.QWEN3, VisionProvider.DOUBAO]
    if provider not in allowed_providers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid vision_provider. Allowed values: {[p.value for p in allowed_providers]}"
        )
    return provider


def _is_public_url(url: str) -> bool:
    url = str(url)
    if not url:
        return False
    if re.match(r"^https?://", url) is None:
        return False
    if url.startswith("http://127.") or url.startswith("https://127."):
        return False
    if url.startswith("http://localhost") or url.startswith("https://localhost"):
        return False
    return True


def _strip_base64_prefix(data: str) -> str:
    return re.sub(r"^data:image/[^;]+;base64,", "", data, flags=re.IGNORECASE)


def validate_images_payload(images: List[Dict[str, Any]], vision_provider: VisionProvider) -> None:
    """Early validation for /grade to reduce invalid calls."""
    if not images:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Images cannot be empty")
    for img in images:
        url = img.get("url")
        b64 = img.get("base64")
        if url:
            if not _is_public_url(url):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Image URL must be public HTTP/HTTPS (no localhost/127)",
                )
        elif b64:
            cleaned = _strip_base64_prefix(b64)
            est_bytes = int(len(cleaned) * 0.75)
            if est_bytes > 20 * 1024 * 1024:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image size exceeds 20MB; use URL")
            if vision_provider == VisionProvider.DOUBAO:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Doubao only supports URL; base64 not accepted")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Each image must provide url or base64")


def generate_job_id() -> str:
    """生成任务ID"""
    return f"job_{uuid.uuid4().hex[:16]}"


def get_idempotency_key(request: Request, x_idempotency_key: Optional[str] = None) -> Optional[str]:
    """获取幂等性键，只接受 Header。"""
    if x_idempotency_key:
        return x_idempotency_key.strip()
    return None


def check_idempotency(idempotency_key: str) -> Optional[GradeResponse]:
    """检查幂等性，如果存在则返回缓存结果"""
    cached = cache_store.get(f"idp:{idempotency_key}")
    if not cached:
        return None
    try:
        return GradeResponse(**cached["response"])
    except Exception:
        return None


def cache_response(idempotency_key: str, response: GradeResponse) -> None:
    """缓存响应结果"""
    cache_store.set(
        f"idp:{idempotency_key}",
        {"response": response.model_dump(), "ts": datetime.now().isoformat()},
        ttl_seconds=IDP_TTL_HOURS * 3600,
    )


async def perform_grading(req: GradeRequest, provider_str: str) -> GradeResponse:
    """执行批改（同步/后台共用）。"""
    vision_client = VisionClient()
    # Vision 分析
    try:
        vision_result = vision_client.analyze(
            images=req.images,
            prompt="请识别并提取作业内容，包括题目、答案和解题步骤",
            provider=req.vision_provider,
        )
    except Exception as e:
        # 返回失败响应，但不抛 500，便于调用方获知
        return GradeResponse(
            wrong_items=[],
            summary="Vision analysis not available",
            subject=req.subject,
            job_id=None,
            status="failed",
            total_items=None,
            wrong_count=None,
            cross_subject_flag=None,
            warnings=[f"Vision analysis failed: {str(e)}"],
        )

    llm_client = LLMClient()
    try:
        if req.subject == Subject.MATH:
            grading_result = llm_client.grade_math(
                text_content=vision_result.text,
                provider=provider_str,
            )
        elif req.subject == Subject.ENGLISH:
            grading_result = llm_client.grade_english(
                text_content=vision_result.text,
                mode=req.mode or SimilarityMode.NORMAL,
                provider=provider_str,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported subject: {req.subject}",
            )
    except Exception as e:
        return GradeResponse(
            wrong_items=[],
            summary=f"LLM grading failed: {str(e)}",
            subject=req.subject,
            job_id=None,
            status="failed",
            total_items=None,
            wrong_count=None,
            cross_subject_flag=None,
            warnings=[f"LLM error: {str(e)}"],
        )

    return GradeResponse(
        wrong_items=grading_result.wrong_items,
        summary=grading_result.summary,
        subject=req.subject,
        job_id=None,
        status="done",
        total_items=grading_result.total_items,
        wrong_count=grading_result.wrong_count,
        cross_subject_flag=grading_result.cross_subject_flag,
        warnings=grading_result.warnings,
    )


async def background_grade(job_id: str, req: GradeRequest, provider_str: str):
    """后台执行批改，更新 job_cache。"""
    try:
        result = await perform_grading(req, provider_str)
        cache_store.set(
            f"job:{job_id}",
            {
                "status": "done",
                "created_at": datetime.now().isoformat(),
                "request": req.model_dump(),
                "result": result.model_dump(),
                "finished_at": datetime.now().isoformat(),
            },
            ttl_seconds=IDP_TTL_HOURS * 3600,
        )
    except Exception as e:
        cache_store.set(
            f"job:{job_id}",
            {
                "status": "failed",
                "created_at": datetime.now().isoformat(),
                "request": req.model_dump(),
                "result": None,
                "error": str(e),
                "finished_at": datetime.now().isoformat(),
            },
            ttl_seconds=IDP_TTL_HOURS * 3600,
        )


def validate_images(images: List[Any], provider: VisionProvider):
    """Early validation of image inputs to fail fast."""
    for idx, img in enumerate(images):
        if img.url:
            url_str = str(img.url)
            if not (url_str.startswith("http://") or url_str.startswith("https://")):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: URL must be HTTP/HTTPS"
                )
            if "localhost" in url_str or "127.0.0.1" in url_str:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: URL must be public (no localhost/127)"
                )
        elif img.base64:
            if provider == VisionProvider.DOUBAO:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: Doubao provider only accepts URLs, not Base64"
                )
            # Estimate size: len * 0.75
            est_size = len(img.base64) * 0.75
            if est_size > 20 * 1024 * 1024:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: Base64 image too large (>20MB), please use URL"
                )


@router.post("/grade", response_model=GradeResponse, status_code=status.HTTP_200_OK)
async def grade_homework(
    req: GradeRequest,
    background_tasks: BackgroundTasks,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """
    批改作业 API (Stub)
    """
    # 1. Early Validation（公共 URL/20MB/Doubao+base64 等）
    # 1. Early Validation
    validate_images(req.images, req.vision_provider)

    # 2. 幂等性校验
    idempotency_key = get_idempotency_key(None, x_idempotency_key)
    if idempotency_key:
        cached_response = check_idempotency(idempotency_key)
        if cached_response:
            return cached_response

    # 3. 决定同步/异步
    is_large_batch = len(req.images) > 5
    provider_str = "silicon" if req.vision_provider == VisionProvider.QWEN3 else "ark"

    if is_large_batch:
        job_id = generate_job_id()
        cache_store.set(
            f"job:{job_id}",
            {
                "status": "processing",
                "created_at": datetime.now().isoformat(),
                "request": req.model_dump(),
                "result": None,
            },
            ttl_seconds=IDP_TTL_HOURS * 3600,
        )
        background_tasks.add_task(background_grade, job_id, req, provider_str)
        return GradeResponse(
            wrong_items=[],
            summary="任务已创建，正在处理中...",
            subject=req.subject,
            job_id=job_id,
            status="processing",
            total_items=None,
            wrong_count=None,
            cross_subject_flag=None,
            warnings=["大批量任务已转为异步处理"],
        )

    try:
        response = await perform_grading(req, provider_str)
        session_for_ctx = req.session_id or req.batch_id
        if session_for_ctx:
            save_mistakes(session_for_ctx, [item for item in response.wrong_items])
        if idempotency_key:
            cache_response(idempotency_key, response)
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


async def chat_stream(
    req: ChatRequest,
    request: Request,
    last_event_id: Optional[str] = Header(None),
) -> AsyncIterator[bytes]:
    """
    SSE流式苏格拉底辅导:
    - heartbeat/chat/done/error事件
    - 5轮对话上限
    - Session 24小时TTL
    - last-event-id支持断线续接(仅用于恢复session)
    """
    llm_client = LLMClient()

    # session恢复或创建；last_event_id 用于断线续接（仅恢复 session_id）
    session_id = req.session_id or last_event_id or f"session_{uuid.uuid4().hex[:8]}"
    now = datetime.now()
    session_data = get_session(session_id)

    # TTL检查，超期则报错
    if session_data and now - session_data["updated_at"] > timedelta(hours=SESSION_TTL_HOURS):
        delete_session(session_id)
        error_msg = json.dumps({"code": "SESSION_EXPIRED", "message": "session expired"})
        yield f"event: error\ndata: {error_msg}\n\n".encode("utf-8")
        yield b"event: done\ndata: {\"status\":\"error\"}\n\n"
        return

    if not session_data:
        # last-event-id 提供但不存在的情况
        if last_event_id and not req.session_id:
            error_msg = json.dumps({"code": "SESSION_NOT_FOUND", "message": "session not found"})
            yield f"event: error\ndata: {error_msg}\n\n".encode("utf-8")
            yield b"event: done\ndata: {\"status\":\"error\"}\n\n"
            return
        session_data = {
            "history": req.history or [],
            "interaction_count": 0,
            "created_at": now,
            "updated_at": now,
            "context_item_ids": normalize_context_ids(req.context_item_ids or []),
        }
        save_session(session_id, session_data)

    # turn limit检查
    if session_data["interaction_count"] >= MAX_SOCRATIC_TURNS:
        yield b"event: heartbeat\ndata: {}\n\n"
        payload = ChatResponse(
            messages=session_data["history"],
            session_id=session_id,
            retry_after_ms=None,
            cross_subject_flag=None,
        )
        yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")
        yield b"event: done\ndata: {\"status\":\"limit_reached\"}\n\n"
        return

    # Heartbeat
    yield b"event: heartbeat\ndata: {}\n\n"

    # 如果提供 last_event_id 且无显式 session_id，尝试重放上一条 assistant 消息，便于客户端续接
    if last_event_id and not req.session_id and session_data["history"]:
        replay_msgs = assistant_tail(session_data["history"], max_messages=3)
        for msg in replay_msgs:
            payload = ChatResponse(
                messages=[msg],
                session_id=session_id,
                retry_after_ms=None,
                cross_subject_flag=None,
            )
            yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")

    try:
        # 目前默认使用 qwen3 (silicon) 作为 LLM，doubao 可作为回退
        provider_str = "silicon"
        current_turn = session_data["interaction_count"]

        # 限制在 0-4 之间传给模型，模型返回的 interaction_count+1 用于更新
        # 构造错题上下文（仅当前批次，基于 context_item_ids，占位可扩展查询具体错题）
        wrong_item_context = None
        ctx_ids = normalize_context_ids(
            session_data.get("context_item_ids") or req.context_item_ids or []
        )
        session_data["context_item_ids"] = ctx_ids
        if ctx_ids:
            wrong_item_context = {"requested_ids": [str(i) for i in ctx_ids]}
            mistakes = session_id and get_mistakes(session_id)
            selected, missing = resolve_context_items(ctx_ids, mistakes)
            if selected:
                wrong_item_context["items"] = selected
            if missing:
                wrong_item_context["missing"] = missing
            if not mistakes:
                wrong_item_context["note"] = "no mistakes cached for this session"

        tutor_result = llm_client.socratic_tutor(
            question=req.question,
            wrong_item_context=wrong_item_context,
            session_id=session_id,
            interaction_count=current_turn,
            provider=provider_str,
        )

        # 更新session，追加本轮问答
        session_data["history"].append({"role": "user", "content": req.question})
        session_data["history"].extend(tutor_result.messages)
        session_data["interaction_count"] = min(tutor_result.interaction_count, MAX_SOCRATIC_TURNS)
        session_data["updated_at"] = datetime.now()
        save_session(session_id, session_data)

        payload = ChatResponse(
            messages=session_data["history"],
            session_id=session_id,
            retry_after_ms=None,
            cross_subject_flag=None,
        )
        yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")
        # 判定状态：达到上限 limit_reached；最后一轮（>=MAX-1）标记 explained；否则沿用模型返回
        status_str = tutor_result.status
        if session_data["interaction_count"] >= MAX_SOCRATIC_TURNS:
            status_str = "limit_reached"
        elif current_turn >= MAX_SOCRATIC_TURNS - 1:
            status_str = "explained"
        yield f"event: done\ndata: {{\"status\":\"{status_str}\",\"session_id\":\"{session_id}\"}}\n\n".encode("utf-8")

    except Exception as e:
        logger.error(f"Chat stream failed: {e}", exc_info=True)
        error_msg = json.dumps({"error": str(e)})
        yield f"event: error\ndata: {error_msg}\n\n".encode("utf-8")
        yield b"event: done\ndata: {\"status\":\"error\"}\n\n"


@router.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    last_event_id: Optional[str] = Header(None),
):
    return StreamingResponse(
        chat_stream(req=req, request=request, last_event_id=last_event_id),
        media_type="text/event-stream",
    )


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = cache_store.get(f"job:{job_id}")
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job
