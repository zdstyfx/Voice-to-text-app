from fastapi import APIRouter
from web.models import HealthResponse

router = APIRouter()


@router.get("/api/health")
async def health() -> HealthResponse:
    return HealthResponse()
