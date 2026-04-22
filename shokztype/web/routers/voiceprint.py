import base64
import threading
import time

import numpy as np
from fastapi import APIRouter, HTTPException

from shokztype.web.web_config import get_config, update_config
from shokztype.web.models import (
    CreateProfileRequest,
    EnrollStepResponse,
    SetActiveProfilesRequest,
)
from shokztype.web.services import voiceprint_manager

router = APIRouter()


# ---------------------------------------------------------------------------
# 后端麦克风录音（与 ASR 同源，保证声纹一致性）
# ---------------------------------------------------------------------------

_enroll_stop = threading.Event()


def _record_from_mic(duration_s: float = 5.0, sample_rate: int = 16000) -> np.ndarray:
    """用 sounddevice 从系统麦克风录制，支持提前中止。使用与 pipeline 相同的设备。"""
    import sounddevice as sd
    from shokztype.web.services.recording_pipeline import _set_state
    from shokztype.web.web_config import get_config

    config = get_config()
    device = config.get("audio", {}).get("device")
    # 转为 int（sounddevice 要求整数索引）
    if isinstance(device, str) and device.isdigit():
        device = int(device)

    _enroll_stop.clear()
    block_ms = 100
    block_samples = int(sample_rate * block_ms / 1000)
    total_samples = int(duration_s * sample_rate)
    chunks = []
    collected = 0

    stream = sd.InputStream(
        samplerate=sample_rate, channels=1, dtype='int16',
        blocksize=block_samples, device=device,
    )
    stream.start()

    try:
        while collected < total_samples and not _enroll_stop.is_set():
            data, _ = stream.read(block_samples)
            chunks.append(data.copy())
            collected += len(data)
            remaining = max(0, (total_samples - collected) / sample_rate)
            _set_state("recording", f"声纹录制中... {remaining:.0f}s")
    finally:
        stream.stop()
        stream.close()

    if not chunks:
        return np.array([], dtype=np.int16)
    return np.concatenate(chunks, axis=0).flatten()


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

    config = get_config()
    if config.get("voiceprint", {}).get("enabled"):
        profiles = voiceprint_manager.list_profiles()
        complete = [p for p in profiles if p.get("enrollment_complete")]
        if not complete:
            update_config({"voiceprint": {"enabled": False, "activeProfiles": []}})
            return {"success": True, "voiceprint_disabled": True}

    return {"success": True}


@router.post("/api/voiceprint/profiles/{profile_id}/enroll")
async def enroll_step(profile_id: str, step: int = 1, duration: float = 5.0) -> EnrollStepResponse:
    """后端录制麦克风音频并做声纹录入（与 ASR 同源，保证一致性）。"""
    import asyncio
    from shokztype.web.services.recording_pipeline import _set_state

    _set_state("recording", f"声纹录制中... {duration:.0f}s")

    loop = asyncio.get_event_loop()
    audio_data = await loop.run_in_executor(None, _record_from_mic, duration)

    _set_state("processing", "声纹分析中...")
    result = await voiceprint_manager.enroll_step(profile_id, step, audio_data)

    _set_state("ready")
    return EnrollStepResponse(**result)


@router.post("/api/voiceprint/enroll/stop")
async def stop_enroll_recording() -> dict:
    """提前结束声纹录制。"""
    _enroll_stop.set()
    return {"success": True}


@router.put("/api/voiceprint/active")
async def set_active(req: SetActiveProfilesRequest) -> dict:
    active = voiceprint_manager.set_active_profiles(req.profile_ids)
    update_config({"voiceprint": {"activeProfiles": active}})
    return {"success": True, "activeProfiles": active}


@router.post("/api/voiceprint/toggle")
async def toggle_voiceprint() -> dict:
    from shokztype.web.services.event_bus import bus

    config = get_config()
    currently_enabled = config.get("voiceprint", {}).get("enabled", False)

    if not currently_enabled:
        profiles = voiceprint_manager.list_profiles()
        complete = [p["id"] for p in profiles if p.get("enrollment_complete")]
        if not complete:
            return {"success": False, "error": "请先录制至少一个声纹档案后再开启"}
        vp_update = {"voiceprint": {"enabled": True, "activeProfiles": complete}}
        update_config(vp_update)
        bus.emit("config_changed", vp_update)
        return {"success": True, "enabled": True, "activeProfiles": complete}

    vp_update = {"voiceprint": {"enabled": False, "activeProfiles": []}}
    update_config(vp_update)
    bus.emit("config_changed", vp_update)
    return {"success": True, "enabled": False, "activeProfiles": []}
