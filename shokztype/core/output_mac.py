"""Text injection for macOS via Quartz CGEvent."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


def type_with_cgevent(payload: str) -> bool:
    try:
        import Quartz
    except ImportError:
        logger.warning("pyobjc-framework-Quartz 未安装")
        return False

    try:
        for char in payload:
            event_down = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
            Quartz.CGEventKeyboardSetUnicodeString(event_down, len(char), char)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event_down)

            event_up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
            Quartz.CGEventKeyboardSetUnicodeString(event_up, len(char), char)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event_up)

            time.sleep(0.005)

        return True
    except Exception as exc:
        logger.warning("CGEvent 文字注入失败: %s", exc)
        return False


def try_clipboard_injection(payload: str) -> bool:
    try:
        import pyperclip
        import Quartz
    except ImportError:
        return False

    try:
        prev_clip = pyperclip.paste()
    except Exception:
        prev_clip = None

    try:
        pyperclip.copy(payload)
        success = _emit_cmd_v()
    except Exception as exc:
        logger.debug("剪贴板注入失败: %s", exc)
        success = False
        # 注入失败时立即恢复
        if prev_clip is not None:
            try:
                pyperclip.copy(prev_clip)
            except Exception:
                pass
        return False

    # 注入成功：延迟恢复，等目标 App 完成 Cmd+V 粘贴后再覆盖剪贴板
    if prev_clip is not None:
        import threading
        def _restore():
            try:
                pyperclip.copy(prev_clip)
            except Exception:
                pass
        threading.Timer(0.5, _restore).start()

    return success


def _emit_cmd_v() -> bool:
    import Quartz

    # kVK_Command = 0x37, kVK_ANSI_V = 0x09
    VK_COMMAND = 0x37
    VK_V = 0x09

    # Command down
    cmd_down = Quartz.CGEventCreateKeyboardEvent(None, VK_COMMAND, True)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, cmd_down)

    # V down with Command flag
    v_down = Quartz.CGEventCreateKeyboardEvent(None, VK_V, True)
    Quartz.CGEventSetFlags(v_down, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, v_down)

    # V up
    v_up = Quartz.CGEventCreateKeyboardEvent(None, VK_V, False)
    Quartz.CGEventSetFlags(v_up, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, v_up)

    # Command up
    cmd_up = Quartz.CGEventCreateKeyboardEvent(None, VK_COMMAND, False)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, cmd_up)

    time.sleep(0.05)
    return True
