"""音频反馈工具：提示音等。"""

import threading


def beep(freq: int, duration_ms: int) -> None:
    """在后台线程播放 Windows 提示音，避免阻塞调用线程。"""
    try:
        import winsound
        threading.Thread(
            target=winsound.Beep, args=(freq, duration_ms), daemon=True
        ).start()
    except Exception:
        pass
