"""Cloud ASR provider factory — 根据配置选择实现。"""

from __future__ import annotations

from typing import Any, Dict


def create_cloud_asr(config: Dict[str, Any]):
    """根据配置创建对应的云端 ASR 实例。

    判断顺序:
      1. asr.backend == "volcengine" → VolcEngineASR
      2. cloud_asr.provider == "volcengine" → VolcEngineASR
      3. 其他 → CloudASR (DashScope)
    """
    backend = config.get("asr", {}).get("backend", "")
    provider = config.get("cloud_asr", {}).get("provider", "dashscope")

    if backend == "volcengine" or provider == "volcengine":
        from .volcengine_asr import VolcEngineASR
        return VolcEngineASR(config)

    from .cloud_asr import CloudASR
    return CloudASR(config)
