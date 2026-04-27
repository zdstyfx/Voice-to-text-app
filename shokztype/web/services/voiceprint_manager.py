"""声纹录制流程编排，对接 shokztype.core.speaker / core.speaker_db 真实实现。"""

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
        from shokztype.core.speaker import SpeakerProcessor
        _speaker_processor = SpeakerProcessor(config)
        _speaker_db = _speaker_processor._db
        logger.info("声纹模块初始化成功")
    except Exception as e:
        import traceback
        logger.warning(f"声纹模块初始化失败（可能缺少模型）: {e}")
        logger.warning(traceback.format_exc())
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
    """删除声纹档案（复用 SpeakerDB.remove）。"""
    if _speaker_db is None:
        return False
    return _speaker_db.remove(name)


async def enroll_step(name: str, step: int, audio_data) -> dict[str, Any]:
    """执行一步声纹录制。audio_data 可以是 np.ndarray (int16) 或 bytes。"""
    if _speaker_processor is None:
        return {"success": False, "step": step, "total": TOTAL_STEPS,
                "quality_score": 0, "message": "声纹模块未初始化"}
    if step < 1 or step > TOTAL_STEPS:
        return {"success": False, "step": step, "total": TOTAL_STEPS,
                "quality_score": 0, "message": f"步骤范围 1-{TOTAL_STEPS}"}

    try:
        if isinstance(audio_data, np.ndarray):
            audio_int16 = audio_data.astype(np.int16) if audio_data.dtype != np.int16 else audio_data
        else:
            audio_int16 = np.frombuffer(audio_data, dtype=np.int16)

        logger.info("声纹录入: 音频长度=%d 样本 (%.2f 秒)", len(audio_int16), len(audio_int16) / 16000)
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
