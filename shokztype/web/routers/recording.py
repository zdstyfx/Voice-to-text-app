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


@router.post("/api/recording/undo")
async def undo_output() -> dict:
    return recording_pipeline.undo_last_output()


@router.get("/api/recording/stream")
async def recording_stream():
    queue = await recording_pipeline.state_subscribe()

    async def event_gen():
        try:
            # 先推一次当前状态（补充 event 字段供前端识别）
            ui = recording_pipeline.get_ui_state()
            ui["event"] = "state"
            yield f"data: {json.dumps(ui, ensure_ascii=False)}\n\n"
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

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
