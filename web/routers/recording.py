from fastapi import APIRouter
from web.services import recording_pipeline

router = APIRouter()


@router.get("/api/recording/status")
async def recording_status() -> dict:
    return recording_pipeline.pipeline_status()


@router.post("/api/recording/restart")
async def restart_pipeline() -> dict:
    return recording_pipeline.restart_pipeline()
