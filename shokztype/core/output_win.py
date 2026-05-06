"""Text injection for Windows via SendInput."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging

logger = logging.getLogger(__name__)

SendInput = ctypes.windll.user32.SendInput
GetMessageExtraInfo = ctypes.windll.user32.GetMessageExtraInfo

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_CONTROL = 0x11
VK_V = 0x56


if hasattr(wintypes, "ULONG_PTR"):
    ULONG_PTR = wintypes.ULONG_PTR  # type: ignore[attr-defined]
else:
    if ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_uint64):
        ULONG_PTR = ctypes.c_uint64
    else:
        ULONG_PTR = ctypes.c_uint32


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [("mi", MouseInput), ("ki", KeyboardInput), ("hi", HardwareInput)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", InputUnion)]


def type_with_unicode(payload: str) -> bool:
    if not payload:
        return True

    n_events = len(payload) * 2
    input_array_type = INPUT * n_events
    inputs = input_array_type()
    extra = GetMessageExtraInfo()

    for i, char in enumerate(payload):
        code_point = ord(char)
        inputs[i * 2] = INPUT(
            type=INPUT_KEYBOARD,
            union=InputUnion(ki=KeyboardInput(
                wVk=0, wScan=code_point,
                dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=extra,
            )),
        )
        inputs[i * 2 + 1] = INPUT(
            type=INPUT_KEYBOARD,
            union=InputUnion(ki=KeyboardInput(
                wVk=0, wScan=code_point,
                dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=extra,
            )),
        )

    sent = SendInput(n_events, ctypes.byref(inputs[0]), ctypes.sizeof(INPUT))
    if sent != n_events:
        logger.warning("SendInput Unicode 批量注入失败，期望 %d 事件，实际 %d", n_events, sent)
        return False
    return True


def try_clipboard_injection(payload: str) -> bool:
    try:
        import pyperclip
    except ImportError:
        return False

    try:
        prev_clip = pyperclip.paste()
    except Exception:
        prev_clip = None

    try:
        pyperclip.copy(payload)
        success = _emit_ctrl_v()
    except Exception as exc:
        logger.debug("剪贴板注入失败: %s", exc)
        success = False
    finally:
        if prev_clip is not None:
            try:
                pyperclip.copy(prev_clip)
            except Exception:
                pass

    return success


def _emit_ctrl_v() -> bool:
    input_array_type = INPUT * 4
    inputs = input_array_type(
        INPUT(
            type=INPUT_KEYBOARD,
            union=InputUnion(
                ki=KeyboardInput(
                    wVk=VK_CONTROL, wScan=0, dwFlags=0,
                    time=0, dwExtraInfo=GetMessageExtraInfo(),
                )
            ),
        ),
        INPUT(
            type=INPUT_KEYBOARD,
            union=InputUnion(
                ki=KeyboardInput(
                    wVk=VK_V, wScan=0, dwFlags=0,
                    time=0, dwExtraInfo=GetMessageExtraInfo(),
                )
            ),
        ),
        INPUT(
            type=INPUT_KEYBOARD,
            union=InputUnion(
                ki=KeyboardInput(
                    wVk=VK_V, wScan=0, dwFlags=KEYEVENTF_KEYUP,
                    time=0, dwExtraInfo=GetMessageExtraInfo(),
                )
            ),
        ),
        INPUT(
            type=INPUT_KEYBOARD,
            union=InputUnion(
                ki=KeyboardInput(
                    wVk=VK_CONTROL, wScan=0, dwFlags=KEYEVENTF_KEYUP,
                    time=0, dwExtraInfo=GetMessageExtraInfo(),
                )
            ),
        ),
    )
    pointer = ctypes.byref(inputs[0])
    sent = SendInput(len(inputs), pointer, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        logger.warning("SendInput Ctrl+V 失败，返回值=%s", sent)
        sent_retry = SendInput(len(inputs), pointer, ctypes.sizeof(INPUT))
        if sent_retry != len(inputs):
            logger.warning("SendInput Ctrl+V 第二次重试失败，返回值=%s", sent_retry)
            return False

    return True
