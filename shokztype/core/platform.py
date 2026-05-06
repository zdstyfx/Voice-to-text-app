"""Platform detection constants."""

import sys
import logging

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

logger = logging.getLogger(__name__)


def get_chinese_font() -> str:
    if IS_MACOS:
        return "PingFang SC"
    return "Microsoft YaHei UI"


def ensure_mac_accessibility() -> bool:
    """macOS: 检查辅助功能权限，未授权则弹出系统提示框引导用户授权。

    返回 True 表示已授权，False 表示未授权（已弹出提示）。
    非 macOS 平台直接返回 True。
    """
    if not IS_MACOS:
        return True

    try:
        import objc
        from ApplicationServices import AXIsProcessTrustedWithOptions
        from Foundation import NSDictionary

        options = NSDictionary.dictionaryWithObject_forKey_(
            True, "AXTrustedCheckOptionPrompt"
        )
        trusted = AXIsProcessTrustedWithOptions(options)
        if not trusted:
            logger.warning("macOS 辅助功能权限未授权，已弹出系统提示")
            try:
                import subprocess
                subprocess.Popen([
                    "open", "x-apple.systempreferences:"
                    "com.apple.preference.security?Privacy_Accessibility"
                ])
            except Exception:
                pass
        return trusted
    except Exception as exc:
        logger.debug("辅助功能权限检查失败: %s", exc)
        return True
