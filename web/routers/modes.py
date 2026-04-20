from fastapi import APIRouter
from web.web_config import get_config, update_config
from web.models import ModeItem, SetCurrentModeRequest

router = APIRouter()

MODES = [
    ModeItem(id="translate", name="翻译", description="将 ASR 文本翻译成目标语言", usesLLM=True),
    ModeItem(id="polish", name="润色", description="整理 ASR 文本为更自然的表达", usesLLM=True),
    ModeItem(id="transcribe", name="转录", description="直接返回转录文本", usesLLM=False),
]
VALID_MODE_IDS = {m.id for m in MODES}


@router.get("/api/modes")
async def list_modes() -> dict:
    config = get_config()
    return {
        "modes": [m.model_dump(by_alias=True) for m in MODES],
        "currentMode": config.get("currentMode", "translate"),
    }


@router.post("/api/modes/current")
async def set_current_mode(req: SetCurrentModeRequest) -> dict:
    if req.mode not in VALID_MODE_IDS:
        return {"success": False, "error": f"无效模式: {req.mode}"}
    config = update_config({"currentMode": req.mode})
    return {"success": True, "currentMode": config["currentMode"]}
