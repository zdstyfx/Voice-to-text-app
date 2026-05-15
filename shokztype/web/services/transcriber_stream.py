"""流式 ASR 转录模块：建立 WebSocket 连接，实时送帧，实时出结果。"""

import itertools
import logging
import threading
from typing import Any

import numpy as np

from shokztype.core.audio_capture import AudioCapture
from shokztype.core.cloud_asr_factory import create_cloud_asr
from shokztype.web.services.event_bus import EventBus

logger = logging.getLogger(__name__)

_CHUNK_FRAMES = 10  # 10 × 20ms = 200ms per chunk
_FINAL_WAIT = 1.5  # stop 后等 sentence 回调的时间（秒），超时则用 partial


class StreamTranscriber:
    """收到 start → 建连 + 实时送帧；收到 stop → 关连接 → emit result + done。"""

    def __init__(self, bus: EventBus, audio: AudioCapture, config: dict[str, Any],
                 input_queue=None) -> None:
        self._bus = bus
        self._audio = audio
        self._input_queue = input_queue
        self._asr = create_cloud_asr(config)
        self._final_text = ""
        self._capture_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._done_emitted = threading.Event()
        self._session_counter = itertools.count(1)
        self._session_id = 0  # 当前会话 ID，用于区分新旧 ASR 回调

        bus.on("start", self._on_start)
        bus.on("stop", self._on_stop)

    def cleanup(self) -> None:
        self._on_stop(None)
        self._bus.off("start", self._on_start)
        self._bus.off("stop", self._on_stop)

    # --- 事件处理 ---

    def _on_start(self, _: Any) -> None:
        # 如果上一个 session 有未提交的结果，先异步提交，避免结果丢失
        prev_text = self._final_text.strip()
        prev_done = self._done_emitted.is_set()
        if prev_text and not prev_done:
            logger.info("新 session 开始，提交上一 session 未完成结果: %s", prev_text[:80])
            prev_bus = self._bus
            def _flush():
                prev_bus.emit("result", prev_text)
                prev_bus.emit("done")
            threading.Thread(target=_flush, daemon=True, name="PrevSessionFlush").start()

        self._session_id = next(self._session_counter)
        sid = self._session_id
        self._final_text = ""
        self._stop_event.clear()
        self._done_emitted.clear()

        # 先启动音频采集（利用 pre-buffer 保留热键前的音频）
        if self._input_queue is None:
            self._bus.emit("state", {"status": "recording"})
            self._audio.start()

        try:
            self._asr.start_streaming(
                on_partial=lambda text, s=sid: self._on_asr_partial(text, s),
                on_sentence=lambda text, s=sid: self._on_asr_sentence(text, s),
            )
        except Exception as e:
            logger.error("流式 ASR 连接失败: %s", e)
            if self._input_queue is None:
                self._audio.stop()
            self._bus.emit("state", {"status": "error", "text": "云端 ASR 连接失败，请检查网络或切换到本地 ASR"})
            self._bus.emit("done")
            return

        logger.info("流式转录已启动 (session=%d)", sid)

        self._capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="StreamCapture",
        )
        self._capture_thread.start()

    def _on_stop(self, _: Any) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        if self._input_queue is None:
            self._audio.stop()

        self._bus.emit("state", {"status": "processing"})
        # 短暂等待 sentence 回调，超时则用当前 partial 文字直接输出
        sid = self._session_id
        threading.Timer(_FINAL_WAIT, lambda: self._finish_if_current(sid)).start()

    def _finish_if_current(self, session_id: int) -> None:
        """定时器触发：只有仍是当前会话才执行。"""
        if session_id != self._session_id:
            return
        self._finish()

    def _finish(self) -> None:
        if self._done_emitted.is_set():
            return
        self._done_emitted.set()

        final = self._final_text.strip()
        if final:
            logger.info("流式转录最终文本: %s", final[:80])
            self._bus.emit("result", final)

        threading.Thread(
            target=self._close_asr, daemon=True, name="StreamASRClose",
        ).start()
        self._bus.emit("done")

    # --- 采集线程 ---

    def _capture_loop(self) -> None:
        frames: list = []
        chunks_sent = 0
        read_queue = self._input_queue if self._input_queue is not None else self._audio.queue
        while True:
            try:
                frame = read_queue.get(timeout=0.05)
            except Exception:
                if self._stop_event.is_set():
                    break
                continue

            if isinstance(frame, np.ndarray):
                frames.append(frame)
            else:
                frames.append(np.frombuffer(frame, dtype=np.int16))

            if len(frames) >= _CHUNK_FRAMES:
                chunk = np.concatenate(frames, axis=0)
                frames.clear()
                self._asr.send_frame(chunk.tobytes())
                chunks_sent += 1
                if chunks_sent == 1:
                    logger.info("首个音频块已发送 (%d samples)", len(chunk))

        logger.info("采集线程退出，共发送 %d 个块", chunks_sent)

        if frames:
            chunk = np.concatenate(frames, axis=0)
            self._asr.send_frame(chunk.tobytes(), is_last=True)
        else:
            self._asr.send_frame(b"", is_last=True)

    # --- ASR 回调 ---

    def _on_asr_partial(self, text: str, session_id: int) -> None:
        if session_id != self._session_id:
            return  # 旧会话的回调，忽略
        if text:
            self._final_text = text
            if not self._stop_event.is_set():
                self._bus.emit("partial", text)

    def _on_asr_sentence(self, text: str, session_id: int) -> None:
        if session_id != self._session_id:
            return  # 旧会话的回调，忽略
        if text:
            self._final_text = text
            logger.info("流式 ASR 句子确认 (session=%d): %s", session_id, text[:80])
        if self._stop_event.is_set():
            self._finish()

    # --- 清理 ---

    def _close_asr(self) -> None:
        try:
            self._asr.stop_streaming()
        except Exception:
            pass
