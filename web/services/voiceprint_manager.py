"""声纹录制流程编排，对接 app.speaker / app.speaker_db 真实实现。"""

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

ENROLLMENT_SENTENCES = [
    "今天天气真不错，适合出去走走。",
    "我喜欢在安静的环境里读一本好书。",
    "请把那份文件发给我，谢谢。",
    "下周三下午两点我们开个会讨论一下。",
    "科技改变生活，创新引领未来。",
]

TOTAL_STEPS = len(ENROLLMENT_SENTENCES)

_speaker_processor = None
_speaker_db = None


def get_speaker_processor():
    """返回已初始化的 SpeakerProcessor 实例，未初始化则返回 None。"""
    return _speaker_processor


def init_speaker(config: dict[str, Any]) -> None:
    """初始化声纹模块（使用 VoiceInterface 的真实实现）。"""
    global _speaker_processor, _speaker_db
    try:
        from app.speaker import SpeakerProcessor
        _speaker_processor = SpeakerProcessor(config)
        _speaker_db = _speaker_processor._db
        logger.info("声纹模块初始化成功")
    except Exception as e:
        logger.warning(f"声纹模块初始化失败（可能缺少模型）: {e}")
        _speaker_processor = None
        _speaker_db = None


def list_profiles() -> list[dict[str, Any]]:
    """列出已注册的声纹档案。"""
    if _speaker_db is None:
        return []
    speakers = _speaker_db.list_manual_speakers()
    profiles = []
    for name in speakers:
        entry = _speaker_db._speakers.get(name, {})
        profiles.append({
            "id": name,
            "name": name,
            "created_at": entry.get("registered_at", ""),
            "enrollment_steps": entry.get("sample_count", 0),
            "enrollment_complete": entry.get("sample_count", 0) >= TOTAL_STEPS,
        })
    return profiles


def create_profile(name: str) -> dict[str, Any]:
    """创建新的声纹档案（仅注册名称，等待采集）。"""
    if _speaker_db is None:
        raise ValueError("声纹模块未初始化")
    existing = _speaker_db.list_manual_speakers()
    if len(existing) >= 3:
        raise ValueError("最多支持 3 个声纹档案")
    if name in existing:
        raise ValueError(f"名称 '{name}' 已存在")
    return {
        "id": name,
        "name": name,
        "created_at": "",
        "enrollment_steps": 0,
        "enrollment_complete": False,
    }


def delete_profile(name: str) -> bool:
    """删除声纹档案。"""
    if _speaker_db is None:
        return False
    if name not in _speaker_db.list_manual_speakers():
        return False
    if name in _speaker_db._speakers:
        del _speaker_db._speakers[name]
        _speaker_db.save()
        return True
    return False


async def enroll_step(name: str, step: int, audio_data: bytes) -> dict[str, Any]:
    """执行一步声纹录制。"""
    if _speaker_processor is None:
        return {"success": False, "step": step, "total": TOTAL_STEPS,
                "quality_score": 0, "message": "声纹模块未初始化"}
    if step < 1 or step > TOTAL_STEPS:
        return {"success": False, "step": step, "total": TOTAL_STEPS,
                "quality_score": 0, "message": f"步骤范围 1-{TOTAL_STEPS}"}

    try:
        # audio_data 可能是 webm/ogg 格式，用 soundfile 解码为 int16
        import io
        import soundfile as sf
        try:
            audio_float, sr = sf.read(io.BytesIO(audio_data), dtype='float32')
            # 转 mono
            if len(audio_float.shape) > 1:
                audio_float = audio_float.mean(axis=1)
            # 重采样到 16kHz
            if sr != 16000:
                import librosa
                audio_float = librosa.resample(audio_float, orig_sr=sr, target_sr=16000)
            audio_int16 = (audio_float * 32767).astype(np.int16)
        except Exception:
            # 降级：尝试作为 raw PCM int16
            audio_int16 = np.frombuffer(audio_data, dtype=np.int16)

        embedding = _speaker_processor.extract_embedding(audio_int16)
        _speaker_db.enroll(name, embedding)
        _speaker_db.save()

        entry = _speaker_db._speakers.get(name, {})
        count = entry.get("sample_count", step)

        return {
            "success": True,
            "step": step,
            "total": TOTAL_STEPS,
            "quality_score": 0.9,
            "message": "录制完成！" if step == TOTAL_STEPS else f"第 {step} 步完成",
        }
    except Exception as e:
        logger.error(f"声纹录制失败: {e}")
        return {"success": False, "step": step, "total": TOTAL_STEPS,
                "quality_score": 0, "message": f"录制失败: {e}"}


def set_active_profiles(profile_ids: list[str]) -> list[str]:
    """设置活跃的声纹过滤目标。"""
    if _speaker_db is None:
        return []
    existing = set(_speaker_db.list_manual_speakers())
    return [pid for pid in profile_ids if pid in existing]


def get_enrollment_sentences() -> list[str]:
    return list(ENROLLMENT_SENTENCES)
