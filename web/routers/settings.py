from fastapi import APIRouter, Request
from web.web_config import get_config, update_config

router = APIRouter()


@router.get("/api/settings")
async def read_settings() -> dict:
    return get_config()


@router.post("/api/settings")
async def save_settings(request: Request) -> dict:
    body = await request.json()
    config = update_config(body)
    return {"success": True, "settings": config}
