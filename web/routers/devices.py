import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from web.services import device_monitor

router = APIRouter()


@router.get("/api/devices")
async def list_devices() -> dict:
    devices = device_monitor.list_devices()
    return {"devices": devices}


@router.get("/api/devices/stream")
async def device_stream():
    queue = await device_monitor.subscribe()

    async def event_generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            device_monitor.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
