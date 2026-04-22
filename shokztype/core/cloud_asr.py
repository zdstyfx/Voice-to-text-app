"""CloudASR — DashScope Paraformer 云端语音识别封装。"""

from __future__ import annotations

import logging
import os
import threading
import time
from http import HTTPStatus
from typing import Any, Callable, Dict, Optional

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
        self._recognition: Optional[object] = None
        self._stream_callback: Optional[_StreamCallback] = None
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

        Recognition.call() 是同步方法，直接返回 RecognitionResult，
        不需要通过回调获取结果。

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

        # Recognition 构造函数要求 callback 参数，但 call() 同步模式不使用它
        recognition = Recognition(
            model=self._model,
            callback=RecognitionCallback(),
            format="wav",
            sample_rate=self._sample_rate,
        )

        start = time.time()
        try:
            logger.info("DashScope ASR 开始调用，文件: %s", wav_path)
            result = recognition.call(
                file=wav_path,
                disfluency_removal_enabled=self._disfluency_removal,
            )
        except Exception as e:
            logger.error("DashScope ASR 调用失败: %s", e)
            return {"success": False, "error": str(e)}
        finally:
            duration = time.time() - start

        if result is None or result.status_code != HTTPStatus.OK:
            error = getattr(result, "message", None) or str(result)
            logger.error("DashScope ASR 返回错误: %s", error)
            return {"success": False, "error": error}

        # 从同步结果中提取识别文本
        sentences = result.get_sentence()
        if sentences and isinstance(sentences, list):
            texts = [s.get("text", "") for s in sentences if RecognitionResult.is_sentence_end(s)]
            full_text = "".join(texts)
        elif sentences and isinstance(sentences, dict):
            full_text = sentences.get("text", "")
        else:
            full_text = ""

        logger.info("DashScope ASR 完成，文本长度: %d, 耗时: %.2fs", len(full_text), duration)
        return {
            "success": True,
            "text": full_text,
            "raw_text": full_text,
            "confidence": 0.95,
            "duration": duration,
        }

    # ------------------------------------------------------------------
    # 流式 API
    # ------------------------------------------------------------------

    def start_streaming(
        self,
        on_partial: Callable[[str], None],
        on_sentence: Callable[[str], None],
    ) -> None:
        """建立 WebSocket 连接，开始流式识别。

        Args:
            on_partial: 中间结果回调（同一句话不断更新的文本）
            on_sentence: 最终结果回调（一句话确认完成）
        """
        import dashscope
        from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

        dashscope.api_key = self._api_key

        callback = _StreamCallback(on_partial, on_sentence)
        self._recognition = Recognition(
            model=self._model,
            callback=callback,
            format=self._format,
            sample_rate=self._sample_rate,
        )
        self._stream_callback = callback

        try:
            self._recognition.start(
                disfluency_removal_enabled=self._disfluency_removal,
            )
            logger.info("DashScope 流式识别已启动")
        except Exception as e:
            logger.error("DashScope 流式识别启动失败: %s", e)
            self._recognition = None
            self._stream_callback = None
            raise

    def send_frame(self, pcm_bytes: bytes) -> None:
        """送入一帧 PCM 音频（int16, 16kHz, mono）。"""
        if self._recognition is None:
            return
        try:
            self._recognition.send_audio_frame(pcm_bytes)
        except Exception as e:
            logger.error("DashScope 送帧失败: %s", e)

    def stop_streaming(self) -> None:
        """结束流式识别，等待 on_complete 回调。"""
        if self._recognition is None:
            return
        try:
            self._recognition.stop()
            logger.info("DashScope 流式识别已停止")
        except Exception as e:
            logger.warning("DashScope 流式识别停止异常: %s", e)
        finally:
            self._recognition = None
            self._stream_callback = None


class _StreamCallback:
    """DashScope Recognition 流式回调，将结果分发给 on_partial / on_sentence。"""

    def __init__(
        self,
        on_partial: Callable[[str], None],
        on_sentence: Callable[[str], None],
    ) -> None:
        self._on_partial = on_partial
        self._on_sentence = on_sentence
        self._completed = threading.Event()
        # 去重状态
        self._last_partial_text = ""
        self._finished_indices: set = set()

    def on_open(self) -> None:
        logger.debug("DashScope 流式连接已打开")

    def on_complete(self) -> None:
        logger.debug("DashScope 流式识别完成")
        self._completed.set()

    def on_error(self, result) -> None:
        logger.error("DashScope 流式识别错误: %s", getattr(result, "message", result))

    def on_close(self) -> None:
        logger.debug("DashScope 流式连接已关闭")

    def on_event(self, result) -> None:
        from dashscope.audio.asr import RecognitionResult

        sentences = result.get_sentence()
        if not sentences:
            return

        # sentences 可能是 list 或 dict
        if isinstance(sentences, dict):
            sentences = [sentences]

        for sentence in sentences:
            text = sentence.get("text", "")
            if not text:
                continue
            is_end = RecognitionResult.is_sentence_end(sentence)
            idx = sentence.get("index", sentence.get("sentence_id"))

            if is_end:
                # 跳过已完成的 sentence index（DashScope 可能重发）
                if idx is not None and idx in self._finished_indices:
                    logger.debug("on_event: 跳过重复 sentence_end idx=%s", idx)
                    continue
                if idx is not None:
                    self._finished_indices.add(idx)
                self._last_partial_text = ""
                self._on_sentence(text)
            else:
                # 跳过重复的 partial（同一文本连续到达）
                if text == self._last_partial_text:
                    continue
                self._last_partial_text = text
                self._on_partial(text)
