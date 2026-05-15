"""热键唤醒模块：监听快捷键切换录音状态 (pynput / helper 子进程)。"""

import logging
import threading

from shokztype.core.hotkeys import PersistentKeyListener
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
        bus.on("start", self._on_start_event)  # 同步 VadKwsWakeup 的启动状态

    def start(self) -> None:
        self._running.set()
        pkl = PersistentKeyListener.get()
        pkl.set_hotkey(self._combo, self._on_press)
        if pkl._use_helper:
            pkl.start_helper(self._combo)
        logger.info("热键唤醒已启动 (combo=%s)", self._combo)

    def stop(self) -> None:
        self._running.clear()
        self._bus.off("done", self._on_done)
        self._bus.off("start", self._on_start_event)
        pkl = PersistentKeyListener.get()
        pkl.clear_hotkey()
        pkl._stop_helper()
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

    def _on_start_event(self, _) -> None:
        """任何模块（包括 VadKwsWakeup）发出 start 时同步本模块状态。"""
        self._active = True
        self._locked = False

    def _on_done(self, _) -> None:
        self._active = False
        self._locked = False
