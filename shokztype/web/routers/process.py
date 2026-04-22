from fastapi import APIRouter
from shokztype.web.web_config import get_config
from shokztype.web.models import ProcessRequest, ProcessResponse
from shokztype.web.services.text_pipeline import process_text

router = APIRouter()


@router.post("/api/process")
async def process(req: ProcessRequest) -> ProcessResponse:
    config = get_config()
    result = await process_text(req.text, config, mode=req.mode)
    return ProcessResponse(**result)
