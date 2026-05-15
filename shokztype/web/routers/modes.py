import uuid
from fastapi import APIRouter, Request
from shokztype.web.web_config import get_config, update_config, DEFAULT_CONFIG
from shokztype.web.models import ModeItem, SetCurrentModeRequest

router = APIRouter()

BUILTIN_MODES = [
    ModeItem(id="transcribe", name="转写",  description="直接返回转写文本",           usesLLM=False),
    ModeItem(id="translate",  name="翻译",  description="将 ASR 文本翻译成目标语言", usesLLM=True),
    ModeItem(id="polish",     name="润色",  description="整理 ASR 文本为更自然的表达", usesLLM=True),
]
BUILTIN_IDS = {m.id for m in BUILTIN_MODES}


def _all_mode_ids(config: dict) -> set[str]:
    custom = {m["id"] for m in config.get("custom_modes", [])}
    return BUILTIN_IDS | custom


_DEFAULT_PROMPTS = DEFAULT_CONFIG.get("prompts", {})


@router.get("/api/modes")
async def list_modes() -> dict:
    config = get_config()
    custom_modes = config.get("custom_modes", [])
    prompts = config.get("prompts", {})
    desc_overrides = config.get("mode_descriptions", {})

    builtin = [
        {
            **m.model_dump(by_alias=True),
            "description": desc_overrides.get(m.id, m.description),
            "prompt": prompts.get(m.id) or _DEFAULT_PROMPTS.get(m.id, ""),
        }
        for m in BUILTIN_MODES
    ]
    custom = [
        {
            "id": m["id"],
            "name": m["name"],
            "description": m.get("description", ""),
            "usesLLM": True,
            "isCustom": True,
            "prompt": prompts.get(m["id"], ""),
        }
        for m in custom_modes
    ]
    return {
        "modes": builtin + custom,
        "currentMode": config.get("currentMode", "translate"),
    }


@router.post("/api/modes/current")
async def set_current_mode(req: SetCurrentModeRequest) -> dict:
    config = get_config()
    if req.mode not in _all_mode_ids(config):
        return {"success": False, "error": f"无效模式: {req.mode}"}
    config = update_config({"currentMode": req.mode})
    from shokztype.web.services import recording_pipeline
    recording_pipeline.set_current_mode(req.mode)
    return {"success": True, "currentMode": config["currentMode"]}


@router.post("/api/modes/custom")
async def create_custom_mode(request: Request) -> dict:
    body = await request.json()
    name = body.get("name", "").strip()
    prompt = body.get("prompt", "").strip()
    if not name:
        return {"success": False, "error": "模式名称不能为空"}

    mode_id = "custom_" + uuid.uuid4().hex[:8]
    config = get_config()
    custom_modes = list(config.get("custom_modes", []))
    custom_modes.append({"id": mode_id, "name": name, "description": name})
    prompts = dict(config.get("prompts", {}))
    prompts[mode_id] = prompt or "# 示例 Prompt（可直接修改）\n你是语音转写纠错专家。修正以下语音识别文字中的错误（同音字误识、断句不自然等），保持原意，只输出修正后的文字：\n\n{text}"
    update_config({"custom_modes": custom_modes, "prompts": prompts})

    # Auto-add default switch keyword "启动{name}"
    try:
        from shokztype.web.routers.wakeup import (
            _rebuild_keywords_file, _read_start_keywords_with_pinyin, _notify_pipeline,
        )
        cfg2 = get_config()
        cmd_kws = dict(cfg2.get("wakeup", {}).get("command_keywords", {}))
        default_kw = "启动" + name
        # Always overwrite to point to the current mode_id (handles stale entries from deleted modes)
        cmd_kws[default_kw] = f"switch_mode:{mode_id}"
        update_config({"wakeup": {"command_keywords": cmd_kws}})
        start_kws = _read_start_keywords_with_pinyin()
        end_names = cfg2.get("wakeup", {}).get("end_keywords", [])
        _rebuild_keywords_file(start_kws, end_names)
        _notify_pipeline()
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).warning("自动添加切换口令失败: %s", exc)

    return {"success": True, "id": mode_id, "name": name}


@router.put("/api/modes/custom/{mode_id}")
async def update_custom_mode(mode_id: str, request: Request) -> dict:
    config = get_config()
    custom_modes = list(config.get("custom_modes", []))
    idx = next((i for i, m in enumerate(custom_modes) if m["id"] == mode_id), None)
    if idx is None:
        return {"success": False, "error": "模式不存在"}

    body = await request.json()
    if "name" in body:
        custom_modes[idx] = {**custom_modes[idx], "name": body["name"], "description": body.get("description", body["name"])}
    elif "description" in body:
        custom_modes[idx] = {**custom_modes[idx], "description": body["description"]}

    updates: dict = {"custom_modes": custom_modes}
    if "prompt" in body:
        prompts = dict(config.get("prompts", {}))
        prompts[mode_id] = body["prompt"]
        updates["prompts"] = prompts

    update_config(updates)
    return {"success": True}


@router.patch("/api/modes/{mode_id}/description")
async def update_mode_description(mode_id: str, request: Request) -> dict:
    body = await request.json()
    description = body.get("description", "").strip()
    config = get_config()
    custom_modes = list(config.get("custom_modes", []))
    idx = next((i for i, m in enumerate(custom_modes) if m["id"] == mode_id), None)
    if idx is not None:
        custom_modes[idx] = {**custom_modes[idx], "description": description}
        update_config({"custom_modes": custom_modes})
    else:
        desc_overrides = dict(config.get("mode_descriptions", {}))
        desc_overrides[mode_id] = description
        update_config({"mode_descriptions": desc_overrides})
    return {"success": True}


@router.delete("/api/modes/custom/{mode_id}")
async def delete_custom_mode(mode_id: str) -> dict:
    config = get_config()
    custom_modes = [m for m in config.get("custom_modes", []) if m["id"] != mode_id]
    prompts = {k: v for k, v in config.get("prompts", {}).items() if k != mode_id}
    # 如果当前模式就是被删除的，重置为 translate
    updates: dict = {"custom_modes": custom_modes, "prompts": prompts}
    if config.get("currentMode") == mode_id:
        updates["currentMode"] = "translate"
        from shokztype.web.services import recording_pipeline
        recording_pipeline.set_current_mode("translate")
    update_config(updates)
    return {"success": True}
