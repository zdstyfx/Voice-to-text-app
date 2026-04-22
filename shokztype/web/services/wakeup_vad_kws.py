"""VAD+KWS 唤醒模块：帧路由器模式。

唯一的 audio.queue 读者。每帧都喂 KWS，激活后同时转发给转录模块。

状态机：
  IDLE   → KWS 命中 → ACTIVE（emit start，开始转发帧）
  ACTIVE → KWS 命中结束词 / 超时 → IDLE（emit stop，停止转发）
"""

import collections
import logging
import queue
import threading
import time
from typing import Any

import numpy as np

from shokztype.core.audio_capture import AudioCapture
from shokztype.core.kws import KwsDetector
from shokztype.web.services.event_bus import EventBus

logger = logging.getLogger(__name__)


class VadKwsWakeup:

    def __init__(
        self,
        bus: EventBus,
        audio: AudioCapture,
        config: dict[str, Any],
    ) -> None:
        self._bus = bus
        self._audio = audio

        self._kws = KwsDetector(config)

        kws_cfg = config.get("kws", {})
        self._active_timeout: float = kws_cfg.get("active_timeout_s", 30)

        self._state = "idle"  # "idle" | "active" | "stopped"
        self._active_since: float = 0.0
        self._running = threading.Event()
        self._main_thread: threading.Thread | None = None

        # 转发队列：ACTIVE 时帧同时进这里，转录模块从这里读
        self.forward_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)

    def start(self) -> None:
        self._state = "idle"
        self._running.set()
        self._audio.start()
        self._bus.emit("state", {"status": "idle"})
        self._main_thread = threading.Thread(
            target=self._main_loop, daemon=True, name="VadKwsMain",
        )
        self._main_thread.start()

    def stop(self) -> None:
        self._state = "stopped"
        self._running.clear()
        self._audio.stop()
        if self._main_thread and self._main_thread.is_alive():
            self._main_thread.join(timeout=3.0)
        if self._kws:
            self._kws.cleanup()
            self._kws = None

    # --- 主循环：唯一的帧读者 ---

    def _main_loop(self) -> None:
        logger.info("VadKws 主循环已启动")
        audio_queue = self._audio.queue

        while self._running.is_set():
            try:
                frame = audio_queue.get(timeout=0.2)
            except Exception:
                if self._state == "active":
                    if time.time() - self._active_since > self._active_timeout:
                        logger.info("KWS ACTIVE 超时 (%.0fs)", self._active_timeout)
                        self._to_idle()
                continue

            if not isinstance(frame, np.ndarray):
                frame = np.frombuffer(frame, dtype=np.int16)

            # KWS 始终运行
            kws_result = self._kws.feed(frame) if self._kws else None

            if self._state == "idle":
                if kws_result:
                    logger.info("KWS 检测到开始词: %s", kws_result.keyword)
                    self._to_active()

            elif self._state == "active":
                # 转发帧给转录模块
                try:
                    self.forward_queue.put_nowait(frame)
                except queue.Full:
                    pass

                # 检测结束词
                if kws_result:
                    logger.info("KWS 检测到结束词: %s", kws_result.keyword)
                    self._to_idle()

                # 超时检查
                if time.time() - self._active_since > self._active_timeout:
                    logger.info("KWS ACTIVE 超时 (%.0fs)", self._active_timeout)
                    self._to_idle()

        logger.info("VadKws 主循环已退出")

    # --- 状态切换 ---

    def _to_active(self) -> None:
        self._state = "active"
        self._active_since = time.time()
        if self._kws:
            self._kws.reset()
        # 清空转发队列
        while not self.forward_queue.empty():
            try:
                self.forward_queue.get_nowait()
            except queue.Empty:
                break
        self._bus.emit("state", {"status": "active"})
        self._bus.emit("start")

    def _to_idle(self) -> None:
        self._state = "idle"
        if self._kws:
            self._kws.reset()
        self._bus.emit("stop")
        self._bus.emit("state", {"status": "idle"})
