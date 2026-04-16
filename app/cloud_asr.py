"""CloudASR — DashScope Paraformer 云端语音识别封装。"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CloudASR:
    """封装 DashScope Recognition SDK，提供与 FunASRServer.transcribe_audio()
    相同返回格式的云端语音识别接口。"""

    def __init__(self, config: Dict[str, Any]) -> None:
        cloud_cfg = config.get("cloud_asr", {})
        self._api_key = self._resolve_api_key(cloud_cfg)
        self._model = cloud_cfg.get("model", "paraformer-realtime-v2")
        self._format = cloud_cfg.get("format", "pcm")
        self._sample_rate = cloud_cfg.get("sample_rate", 16000)
        self._disfluency_removal = cloud_cfg.get("disfluency_removal", False)
        logger.info("CloudASR 初始化完成，模型: %s", self._model)

    @staticmethod
    def _resolve_api_key(cloud_cfg: Dict[str, Any]) -> str:
        key = cloud_cfg.get("api_key", "")
        if key:
            return key
        key = os.environ.get("DASHSCOPE_API_KEY", "")
        if key:
            return key
        raise ValueError(
            "DashScope API key 未配置。"
            "请在 config.json 的 cloud_asr.api_key 中设置，"
            "或设置环境变量 DASHSCOPE_API_KEY。"
        )

    def transcribe_file(self, wav_path: str) -> Dict[str, Any]:
        """同步识别音频文件，返回与 FunASRServer.transcribe_audio() 相同格式的字典。

        返回:
            {"success": bool, "text": str, "raw_text": str,
             "confidence": float, "duration": float, "error": str|None}
        """
        import dashscope
        from dashscope.audio.asr import (
            Recognition,
            RecognitionCallback,
            RecognitionResult,
        )

        dashscope.api_key = self._api_key

        sentences: List[str] = []
        error_msg: Optional[str] = None
        completed = threading.Event()

        class _Callback(RecognitionCallback):
            def on_event(self, result: RecognitionResult) -> None:
                sentence = result.get_sentence()
                if sentence and RecognitionResult.is_sentence_end(sentence):
                    text = sentence.get("text", "")
                    if text:
                        sentences.append(text)

            def on_complete(self) -> None:
                completed.set()

            def on_error(self, result: RecognitionResult) -> None:
                nonlocal error_msg
                error_msg = str(result)
                completed.set()

        callback = _Callback()
        recognition = Recognition(
            model=self._model,
            callback=callback,
            format="wav",
            sample_rate=self._sample_rate,
        )

        start = time.time()
        try:
            recognition.call(
                file=wav_path,
                disfluency_removal_enabled=self._disfluency_removal,
            )
            completed.wait(timeout=60)
        except Exception as e:
            logger.error("DashScope ASR 调用失败: %s", e)
            return {"success": False, "error": str(e)}
        finally:
            duration = time.time() - start

        if error_msg:
            return {"success": False, "error": error_msg}

        full_text = "".join(sentences)
        return {
            "success": True,
            "text": full_text,
            "raw_text": full_text,
            "confidence": 0.95,
            "duration": duration,
        }
