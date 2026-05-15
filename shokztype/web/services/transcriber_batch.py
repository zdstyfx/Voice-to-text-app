"""批量 ASR 转录模块：录音结束后一次性送 ASR 转写。

支持本地 FunASR 和云端批量接口（DashScope/VolcEngine transcribe_file）。
"""

import logging
import os
import tempfile
import threading
import time
import wave
from typing import Any

import numpy as np

from shokztype.core.audio_capture import AudioCapture
from shokztype.web.services.event_bus import EventBus

logger = logging.getLogger(__name__)


class BatchTranscriber:
    """收到 start → 录音攒帧；收到 stop → 拼接 → ASR 转写 → emit result + done。"""

    def __init__(self, bus: EventBus, audio: AudioCapture, config: dict[str, Any],
                 input_queue=None) -> None:
        self._bus = bus
        self._audio = audio
        self._input_queue = input_queue
        self._config = config
        self._frames: list[np.ndarray] = []
        self._capture_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # 初始化 ASR 引擎
        asr_backend = config.get("asr", {}).get("backend", "local")
        self._asr_backend = asr_backend

        if asr_backend in ("cloud", "volcengine"):
            from shokztype.core.cloud_asr_factory import create_cloud_asr
            self._cloud_asr = create_cloud_asr(config)
            self._fun_server = None
        else:
            # 懒加载：ensure_funasr_loaded 首次调用加载模型，后续复用
            from shokztype.web.services.recording_pipeline import ensure_funasr_loaded
            ensure_funasr_loaded()
            from shokztype.core.funasr_server import FunASRServer
            self._fun_server = FunASRServer()  # 复用 patch 已安装，拿缓存实例
            self._cloud_asr = None

        bus.on("start", self._on_start)
        bus.on("stop", self._on_stop)

    def cleanup(self) -> None:
        self._on_stop(None)
        self._bus.off("start", self._on_start)
        self._bus.off("stop", self._on_stop)

    # --- 事件处理 ---

    def _on_start(self, _: Any) -> None:
        self._frames.clear()
        self._stop_event.clear()

        if self._input_queue is None:
            self._bus.emit("state", {"status": "recording"})
            self._audio.start()

        self._capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="BatchCapture",
        )
        self._capture_thread.start()
        logger.info("批量录音已启动")

    def _on_stop(self, _: Any) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        if self._input_queue is None:
            self._audio.stop()
        # join + 转写在后台执行，避免阻塞 EventBus 派发
        threading.Thread(target=self._finish_stop, daemon=True, name="BatchStop").start()

    def _finish_stop(self) -> None:
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=3.0)
        self._capture_thread = None

        # 在后台线程做 ASR 转写（可能耗时几秒）
        frames = list(self._frames)
        self._frames.clear()
        if frames:
            self._bus.emit("state", {"status": "processing"})
            threading.Thread(
                target=self._transcribe, args=(frames,),
                daemon=True, name="BatchTranscribe",
            ).start()
        else:
            logger.info("无有效音频，跳过转写")
            self._bus.emit("done")

    # --- 采集线程 ---

    def _capture_loop(self) -> None:
        read_queue = self._input_queue if self._input_queue is not None else self._audio.queue
        while True:
            try:
                frame = read_queue.get(timeout=0.05)
            except Exception:
                if self._stop_event.is_set():
                    break
                continue

            if isinstance(frame, np.ndarray):
                self._frames.append(frame)
            else:
                self._frames.append(np.frombuffer(frame, dtype=np.int16))

    # --- ASR 转写（后台线程） ---

    def _transcribe(self, frames: list[np.ndarray]) -> None:
        combined = np.concatenate(frames)
        duration_s = len(combined) / 16000.0
        logger.info("开始转写 (%.1f 秒音频)", duration_s)

        fd, tmp_path = tempfile.mkstemp(prefix="asr_batch_", suffix=".wav")
        os.close(fd)
        try:
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(combined.tobytes())

            start_t = time.time()
            if self._asr_backend in ("cloud", "volcengine"):
                asr_result = self._cloud_asr.transcribe_file(tmp_path)
            else:
                asr_result = self._fun_server.transcribe_audio(
                    tmp_path, options=self._config.get("asr"),
                )
            latency = time.time() - start_t

            if asr_result.get("success"):
                text = asr_result.get("text", "").strip()
                logger.info("转写完成 (%.2fs): %s", latency, text[:80])
                if text:
                    self._bus.emit("result", text)
            else:
                error = asr_result.get("error", "unknown")
                logger.error("转写失败: %s", error)
                self._bus.emit("state", {"status": "error", "text": "转写失败"})
        except Exception as e:
            logger.error("ASR 调用异常: %s", e)
            self._bus.emit("state", {"status": "error", "text": str(e)})
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            self._bus.emit("done")
