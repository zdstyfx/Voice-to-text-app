"""Text injection — platform dispatcher."""

from __future__ import annotations

import logging

from shokztype.core.platform import IS_WINDOWS, IS_MACOS

logger = logging.getLogger(__name__)


def type_text(text: str, append_newline: bool = False, method: str = "auto") -> None:
    if not text:
        return

    payload = text + ("\r\n" if append_newline else "")
    logger.debug("注入文本: %s", payload)

    method = (method or "auto").lower()
    if method == "clipboard":
        order = ["clipboard", "unicode"]
    elif method == "unicode":
        order = ["unicode"]
    else:
        order = ["clipboard", "unicode"]

    for mode in order:
        if mode == "clipboard" and _try_clipboard(payload):
            return
        if mode == "unicode" and _try_unicode(payload):
            return

    logger.error("所有文本注入方式均失败: %s", payload)


def _try_unicode(payload: str) -> bool:
    if IS_WINDOWS:
        from shokztype.core.output_win import type_with_unicode
        return type_with_unicode(payload)
    elif IS_MACOS:
        from shokztype.core.output_mac import type_with_cgevent
        return type_with_cgevent(payload)
    else:
        logger.warning("不支持的平台")
        return False


def _try_clipboard(payload: str) -> bool:
    if IS_WINDOWS:
        from shokztype.core.output_win import try_clipboard_injection
        return try_clipboard_injection(payload)
    elif IS_MACOS:
        from shokztype.core.output_mac import try_clipboard_injection
        return try_clipboard_injection(payload)
    else:
        logger.warning("不支持的平台")
        return False
