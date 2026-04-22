import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from shokztype.web.services import recording_pipeline

router = APIRouter()


@router.get("/api/recording/status")
async def recording_status() -> dict:
    return recording_pipeline.pipeline_status()


@router.post("/api/recording/restart")
async def restart_pipeline() -> dict:
    return recording_pipeline.restart_pipeline()


@router.get("/api/recording/stream")
async def recording_stream():
    queue = await recording_pipeline.state_subscribe()

    async def event_gen():
        try:
            # 先推一次当前状态
            init = json.dumps(recording_pipeline.get_ui_state(), ensure_ascii=False)
            yield f"data: {init}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            recording_pipeline.state_unsubscribe(queue)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
