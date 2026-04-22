"""热键唤醒模块：监听 F2 切换录音状态。"""

import logging
import threading

import keyboard

from shokztype.web.services.event_bus import EventBus

logger = logging.getLogger(__name__)


class HotkeyWakeup:
    """按 F2 → emit start；再按 F2 → emit stop。"""

    def __init__(self, bus: EventBus, audio=None, combo: str = "f2") -> None:
        self._bus = bus
        self._combo = combo
        self._active = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._listen, daemon=True, name="HotkeyWakeup",
        )
        self._thread.start()

    def stop(self) -> None:
        keyboard.unhook_all()

    def _listen(self) -> None:
        keyboard.add_hotkey(self._combo, self._on_press, suppress=True)
        logger.info("热键唤醒已启动 (combo=%s)", self._combo)
        keyboard.wait()

    def _on_press(self) -> None:
        if self._active:
            self._active = False
            logger.info("热键: 停止录音")
            self._bus.emit("stop")
        else:
            self._active = True
            logger.info("热键: 开始录音")
            self._bus.emit("start")
