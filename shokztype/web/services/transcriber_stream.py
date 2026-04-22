"""流式 ASR 转录模块：建立 WebSocket 连接，实时送帧，实时出结果。"""

import logging
import threading
from typing import Any

import numpy as np

from shokztype.core.audio_capture import AudioCapture
from shokztype.core.cloud_asr_factory import create_cloud_asr
from shokztype.web.services.event_bus import EventBus

logger = logging.getLogger(__name__)

_CHUNK_FRAMES = 10  # 10 × 20ms = 200ms per chunk


class StreamTranscriber:
    """收到 start → 建连 + 实时送帧；收到 stop → 关连接 → emit result + done。"""

    def __init__(self, bus: EventBus, audio: AudioCapture, config: dict[str, Any],
                 input_queue=None) -> None:
        self._bus = bus
        self._audio = audio
        self._input_queue = input_queue  # VAD 模式：从转发队列读；热键模式：None → 从 audio.queue 读
        self._asr = create_cloud_asr(config)
        self._final_text = ""
        self._capture_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._final_ready = threading.Event()  # ASR 返回 is_last 之后的最终结果时置位

        bus.on("start", self._on_start)
        bus.on("stop", self._on_stop)

    def cleanup(self) -> None:
        self._on_stop(None)
        self._bus.off("start", self._on_start)
        self._bus.off("stop", self._on_stop)

    # --- 事件处理 ---

    def _on_start(self, _: Any) -> None:
        self._final_text = ""
        self._stop_event.clear()
        self._final_ready.clear()

        # 建立 ASR WebSocket 连接
        try:
            self._asr.start_streaming(
                on_partial=self._on_asr_partial,
                on_sentence=self._on_asr_sentence,
            )
        except Exception as e:
            logger.error("流式 ASR 连接失败: %s", e)
            self._bus.emit("state", {"status": "error", "text": "ASR 连接失败"})
            self._bus.emit("done")
            return

        # 热键模式：自己管音频采集；VAD 模式：音频由 VadKwsWakeup 管
        if self._input_queue is None:
            self._bus.emit("state", {"status": "recording"})
            self._audio.start()
        logger.info("流式转录已启动")

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

        # 等待采集线程结束（会发 is_last）
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=3.0)
        self._capture_thread = None

        # 等待 ASR 返回最终结果（capture 线程发完 is_last 后，服务端会返回最终 sentence）
        self._final_ready.wait(timeout=5.0)

        # 输出最终文本
        text = self._final_text.strip()
        if text:
            logger.info("流式转录最终文本: %s", text[:80])
            self._bus.emit("result", text)

        # 后台关闭 ASR 连接
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

        # 剩余帧作为最后一包
        if frames:
            chunk = np.concatenate(frames, axis=0)
            self._asr.send_frame(chunk.tobytes(), is_last=True)
        else:
            self._asr.send_frame(b"", is_last=True)

    # --- ASR 回调 ---

    def _on_asr_partial(self, text: str) -> None:
        if text:
            self._final_text = text
            if not self._stop_event.is_set():
                self._bus.emit("partial", text)

    def _on_asr_sentence(self, text: str) -> None:
        if text:
            self._final_text = text
            logger.info("流式 ASR 句子确认: %s", text[:80])
        # is_last 发出后收到的 sentence 就是最终结果
        if self._stop_event.is_set():
            self._final_ready.set()

    # --- 清理 ---

    def _close_asr(self) -> None:
        try:
            self._asr.stop_streaming()
        except Exception:
            pass
