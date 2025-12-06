from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from typing import AsyncIterator

from homework_agent.models.schemas import GradeRequest, GradeResponse, ChatRequest, ChatResponse
from homework_agent.services.vision import VisionClient
from homework_agent.services.llm import LLMClient  # placeholder, to be implemented

router = APIRouter()


@router.post("/grade", response_model=GradeResponse)
async def grade(req: GradeRequest):
    # TODO: add idempotency check, sync/async branching, job queue
    vision = VisionClient()
    try:
        vision_result = vision.analyze(req.images, prompt=None, provider=req.vision_provider)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    # TODO: call LLM grading logic (math/english) using vision_result
    # Placeholder response
    return GradeResponse(
        wrong_items=[],
        summary="Processing not yet implemented",
        subject=req.subject,
        job_id=None,
        status="processing",
        total_items=None,
        wrong_count=None,
        cross_subject_flag=None,
        warnings=["stub implementation"],
    )


async def chat_stream(req: ChatRequest) -> AsyncIterator[bytes]:
    # TODO: implement SSE streaming with 5-turn limit
    # Heartbeat
    yield b"event: heartbeat\ndata: {}\n\n"
    payload = ChatResponse(
        messages=[{"role": "assistant", "content": "Stub response"}],
        session_id=req.session_id,
        retry_after_ms=None,
        cross_subject_flag=None,
    )
    yield f"event: chat\ndata: {payload.json()}\n\n".encode("utf-8")
    yield b"event: done\ndata: {\"status\":\"continue\"}\n\n"


@router.post("/chat")
async def chat(req: ChatRequest):
    return StreamingResponse(chat_stream(req), media_type="text/event-stream")


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    # TODO: implement job status lookup
    return {"job_id": job_id, "status": "processing"}
