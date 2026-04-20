import base64

from fastapi import APIRouter, HTTPException

from web.web_config import get_config, update_config
from web.models import (
    CreateProfileRequest,
    EnrollStepRequest,
    EnrollStepResponse,
    SetActiveProfilesRequest,
)
from web.services import voiceprint_manager

router = APIRouter()


@router.get("/api/voiceprint/profiles")
async def list_profiles() -> dict:
    config = get_config()
    vp = config.get("voiceprint", {})
    profiles = voiceprint_manager.list_profiles()
    return {
        "enabled": vp.get("enabled", False),
        "profiles": profiles,
        "activeProfiles": vp.get("activeProfiles", []),
        "sentences": voiceprint_manager.get_enrollment_sentences(),
    }


@router.post("/api/voiceprint/profiles")
async def create_profile(req: CreateProfileRequest) -> dict:
    try:
        profile = voiceprint_manager.create_profile(req.name)
        return {"success": True, "profile": profile}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/voiceprint/profiles/{profile_id}")
async def delete_profile(profile_id: str) -> dict:
    ok = voiceprint_manager.delete_profile(profile_id)
    if not ok:
        raise HTTPException(status_code=404, detail="声纹档案不存在")

    # 删除后检查：如果没有已完成的档案了，自动关闭声纹
    config = get_config()
    if config.get("voiceprint", {}).get("enabled"):
        profiles = voiceprint_manager.list_profiles()
        complete = [p for p in profiles if p.get("enrollment_complete")]
        if not complete:
            update_config({"voiceprint": {"enabled": False, "activeProfiles": []}})
            return {"success": True, "voiceprint_disabled": True}

    return {"success": True}


@router.post("/api/voiceprint/profiles/{profile_id}/enroll")
async def enroll_step(profile_id: str, req: EnrollStepRequest) -> EnrollStepResponse:
    audio_data = base64.b64decode(req.audio_base64)
    result = await voiceprint_manager.enroll_step(profile_id, req.step, audio_data)
    return EnrollStepResponse(**result)


@router.put("/api/voiceprint/active")
async def set_active(req: SetActiveProfilesRequest) -> dict:
    active = voiceprint_manager.set_active_profiles(req.profile_ids)
    update_config({"voiceprint": {"activeProfiles": active}})
    return {"success": True, "activeProfiles": active}


@router.post("/api/voiceprint/toggle")
async def toggle_voiceprint() -> dict:
    config = get_config()
    currently_enabled = config.get("voiceprint", {}).get("enabled", False)

    if not currently_enabled:
        # 开启时校验 + 自动激活所有已完成档案
        profiles = voiceprint_manager.list_profiles()
        complete = [p["id"] for p in profiles if p.get("enrollment_complete")]
        if not complete:
            return {"success": False, "error": "请先录制至少一个声纹档案后再开启"}
        update_config({"voiceprint": {"enabled": True, "activeProfiles": complete}})
        return {"success": True, "enabled": True, "activeProfiles": complete}

    update_config({"voiceprint": {"enabled": False, "activeProfiles": []}})
    return {"success": True, "enabled": False, "activeProfiles": []}
