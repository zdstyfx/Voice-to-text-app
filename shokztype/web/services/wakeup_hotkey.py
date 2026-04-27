"""热键唤醒模块：监听 F2 切换录音状态。"""

import logging
import threading

import keyboard

from shokztype.web.services.event_bus import EventBus

logger = logging.getLogger(__name__)


class HotkeyWakeup:

    def __init__(self, bus: EventBus, audio=None, combo: str = "f2") -> None:
        self._bus = bus
        self._combo = combo
        self._active = False
        self._locked = False
        self._running = threading.Event()

        bus.on("done", self._on_done)

    def start(self) -> None:
        self._running.set()
        keyboard.add_hotkey(self._combo, self._on_press, suppress=True)
        logger.info("热键唤醒已启动 (combo=%s)", self._combo)

    def stop(self) -> None:
        self._running.clear()
        self._bus.off("done", self._on_done)
        try:
            keyboard.remove_hotkey(self._combo)
        except (KeyError, ValueError):
            pass
        self._active = False
        self._locked = False

    def _on_press(self) -> None:
        if not self._running.is_set():
            return
        if self._locked:
            return
        if self._active:
            self._active = False
            self._locked = True
            logger.info("热键: 停止录音")
            self._bus.emit("stop")
        else:
            self._active = True
            logger.info("热键: 开始录音")
            self._bus.emit("start")

    def _on_done(self, _) -> None:
        self._locked = False
