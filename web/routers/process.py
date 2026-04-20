from fastapi import APIRouter
from web.web_config import get_config
from web.models import ProcessRequest, ProcessResponse
from web.services.text_pipeline import process_text

router = APIRouter()


@router.post("/api/process")
async def process(req: ProcessRequest) -> ProcessResponse:
    config = get_config()
    result = await process_text(req.text, config, mode=req.mode)
    return ProcessResponse(**result)
