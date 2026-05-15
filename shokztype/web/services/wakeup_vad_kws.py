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
from typing import Any, Optional

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
            config.get("wakeup", {}).get("end_keywords", ["退出", "结束"])
        )
        self._command_keywords: dict[str, str] = dict(
            config.get("wakeup", {}).get("command_keywords", {"撤销": "undo"})
        )

        self._state = "idle"  # "idle" | "active" | "locked" | "stopped"
        self._active_since: float = 0.0
        self._running = threading.Event()
        self._main_thread: threading.Thread | None = None
        self._enrollment_active: bool = False
        self._speaker_gate: Optional[Any] = None  # 由 pipeline 注入，用于验证结束词

        self.forward_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)

        bus.on("done", self._on_done)
        bus.on("start", self._on_external_start)
        bus.on("stop", self._on_external_stop)
        bus.on("enrollment_start", lambda _: setattr(self, "_enrollment_active", True))
        bus.on("enrollment_stop", lambda _: setattr(self, "_enrollment_active", False))

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
        self._bus.off("start", self._on_external_start)
        self._bus.off("stop", self._on_external_stop)
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
                if not self._enrollment_active and kws_result:
                    kw = kws_result.keyword
                    if kw in self._command_keywords:
                        action = self._command_keywords[kw]
                        logger.info("KWS 命令词: %s → %s", kw, action)
                        self._bus.emit("command", {"action": action})
                    elif kw not in self._end_keywords:
                        logger.info("KWS 检测到开始词: %s", kw)
                        self._to_active()

            elif self._state == "active":
                try:
                    self.forward_queue.put_nowait(frame)
                except queue.Full:
                    pass

                if kws_result and kws_result.keyword in self._end_keywords:
                    if self._speaker_approved():
                        logger.info("KWS 检测到结束词: %s", kws_result.keyword)
                        self._to_locked()
                    else:
                        logger.info("KWS 结束词 '%s' 忽略：声纹未验证（可能为他人声音）", kws_result.keyword)

                if time.time() - self._active_since > self._active_timeout:
                    logger.info("KWS ACTIVE 超时 (%.0fs)", self._active_timeout)
                    self._to_locked()

            elif self._state == "locked":
                # 等待 done 解锁，期间继续读帧（不堵队列）但不转发也不检测
                pass

        logger.info("VadKws 主循环已退出")

    # --- 状态切换 ---

    def _speaker_approved(self) -> bool:
        """声纹 gate 未启用时始终返回 True；启用时检查最近 4 秒内是否验证通过。"""
        if self._speaker_gate is None:
            return True
        return (time.time() - self._speaker_gate.last_approval_time) < 4.0

    def _to_active(self) -> None:
        self._to_active_state()
        self._bus.emit("start")

    def _to_active_state(self) -> None:
        """切换到 active 状态但不重新 emit start（避免外部触发时死循环）。"""
        self._state = "active"
        self._active_since = time.time()
        # 不在此处 reset KWS stream：feed() 检测到关键词后内部已调 reset_stream()，
        # stream 保有上下文，可立即识别结束词；create_stream() 会引入预热延迟。
        while not self.forward_queue.empty():
            try:
                self.forward_queue.get_nowait()
            except queue.Empty:
                break
        self._bus.emit("state", {"status": "active"})

    def _to_locked(self) -> None:
        """停止转发，等 ASR 完成后才回到 idle。"""
        self._to_locked_state()
        self._bus.emit("stop")

    def _to_locked_state(self) -> None:
        """切换到 locked 状态但不重新 emit stop（避免外部触发时死循环）。"""
        self._state = "locked"
        if self._kws:
            self._kws.reset()
        self._bus.emit("state", {"status": "processing"})

    def _on_external_start(self, _) -> None:
        """响应外部 start 事件（如热键），如在 idle 则进入 active 并开始转发帧。"""
        if self._state == "idle":
            self._to_active_state()

    def _on_external_stop(self, _) -> None:
        """响应外部 stop 事件（如热键），如在 active 则进入 locked 等待 ASR。"""
        if self._state == "active":
            self._to_locked_state()

    def _on_done(self, _: Any) -> None:
        """ASR 完成，解锁回到 idle。"""
        if self._state == "locked":
            self._state = "idle"
            self._bus.emit("state", {"status": "idle"})
            logger.info("KWS 解锁，回到 IDLE")
