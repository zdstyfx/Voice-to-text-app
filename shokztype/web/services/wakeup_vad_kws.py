"""VAD+KWS 唤醒模块：帧路由器模式。

唯一的 audio.queue 读者。每帧都喂 KWS，激活后同时转发给转录模块。

状态机：
  IDLE    → KWS 命中开始词 → ACTIVE（emit start，开始转发帧）
  ACTIVE  → KWS 命中结束词 / 超时 → LOCKED（emit stop，停止转发）
  LOCKED  → 收到 done → IDLE（ASR 已完成，恢复监听）
"""

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
        self._end_keywords: set[str] = set(
            config.get("wakeup", {}).get("end_keywords", [])
        )

        self._state = "idle"  # "idle" | "active" | "locked" | "stopped"
        self._active_since: float = 0.0
        self._running = threading.Event()
        self._main_thread: threading.Thread | None = None

        self.forward_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)

        bus.on("done", self._on_done)

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
        self._bus.off("done", self._on_done)
        if self._main_thread and self._main_thread.is_alive():
            self._main_thread.join(timeout=3.0)
        if self._kws:
            self._kws.cleanup()
            self._kws = None

    # --- 主循环 ---

    def _main_loop(self) -> None:
        logger.info("VadKws 主循环已启动")
        audio_queue = self._audio.queue
        _frame_count = 0

        while self._running.is_set():
            try:
                frame = audio_queue.get(timeout=0.2)
            except Exception:
                if self._state == "active":
                    if time.time() - self._active_since > self._active_timeout:
                        logger.info("KWS ACTIVE 超时 (%.0fs)", self._active_timeout)
                        self._to_locked()
                continue

            if not isinstance(frame, np.ndarray):
                frame = np.frombuffer(frame, dtype=np.int16)

            _frame_count += 1
            if _frame_count % 250 == 1:  # 每 5 秒一次
                rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
                logger.info("VadKws frame#%d dtype=%s shape=%s RMS=%.0f qsize=%d",
                            _frame_count, frame.dtype, frame.shape, rms, audio_queue.qsize())

            kws_result = self._kws.feed(frame) if self._kws else None

            if self._state == "idle":
                if kws_result and kws_result.keyword not in self._end_keywords:
                    logger.info("KWS 检测到开始词: %s", kws_result.keyword)
                    self._to_active()

            elif self._state == "active":
                try:
                    self.forward_queue.put_nowait(frame)
                except queue.Full:
                    pass

                if kws_result and kws_result.keyword in self._end_keywords:
                    logger.info("KWS 检测到结束词: %s", kws_result.keyword)
                    self._to_locked()

                if time.time() - self._active_since > self._active_timeout:
                    logger.info("KWS ACTIVE 超时 (%.0fs)", self._active_timeout)
                    self._to_locked()

            elif self._state == "locked":
                # 等待 done 解锁，期间继续读帧（不堵队列）但不转发也不检测
                pass

        logger.info("VadKws 主循环已退出")

    # --- 状态切换 ---

    def _to_active(self) -> None:
        self._state = "active"
        self._active_since = time.time()
        if self._kws:
            self._kws.reset()
        while not self.forward_queue.empty():
            try:
                self.forward_queue.get_nowait()
            except queue.Empty:
                break
        self._bus.emit("state", {"status": "active"})
        self._bus.emit("start")

    def _to_locked(self) -> None:
        """停止转发，等 ASR 完成后才回到 idle。"""
        self._state = "locked"
        if self._kws:
            self._kws.reset()
        self._bus.emit("stop")
        self._bus.emit("state", {"status": "processing"})

    def _on_done(self, _: Any) -> None:
        """ASR 完成，解锁回到 idle。"""
        if self._state == "locked":
            self._state = "idle"
            self._bus.emit("state", {"status": "idle"})
            logger.info("KWS 解锁，回到 IDLE")
