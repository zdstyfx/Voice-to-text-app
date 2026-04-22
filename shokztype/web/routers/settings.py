from fastapi import APIRouter, Request
from shokztype.web.web_config import get_config, update_config
from shokztype.web.services.event_bus import bus

router = APIRouter()


@router.get("/api/settings")
async def read_settings() -> dict:
    return get_config()


@router.post("/api/settings")
async def save_settings(request: Request) -> dict:
    body = await request.json()
    config = update_config(body)
    bus.emit("config_changed", body)
    return {"success": True, "settings": config}
