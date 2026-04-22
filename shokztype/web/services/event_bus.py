"""线程安全的发布-订阅消息总线（全局单例）。"""

import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventBus:
    """极简 EventBus：同步回调，线程安全。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = {}
        self._lock = threading.Lock()

    def on(self, event: str, callback: Callable) -> None:
        with self._lock:
            self._handlers.setdefault(event, []).append(callback)

    def off(self, event: str, callback: Callable) -> None:
        with self._lock:
            handlers = self._handlers.get(event, [])
            if callback in handlers:
                handlers.remove(callback)

    def emit(self, event: str, data: Any = None) -> None:
        with self._lock:
            handlers = list(self._handlers.get(event, []))
        for handler in handlers:
            try:
                handler(data)
            except Exception:
                logger.exception("EventBus handler error on '%s'", event)

    def clear(self) -> None:
        """清除所有订阅。"""
        with self._lock:
            self._handlers.clear()


# 全局单例
bus = EventBus()
