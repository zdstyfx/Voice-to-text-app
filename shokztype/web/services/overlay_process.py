"""独立进程运行的状态浮窗。通过 UDP 接收状态更新。

启动方式：python -m shokztype.web.services.overlay_process [--port 9123]
主进程通过 UDP 发送 JSON 消息来更新显示。
"""

import ctypes
import json
import socket
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont

UDP_PORT = 0  # 由父进程通过 --port 参数传入

STYLES = {
    "loading":    {"bg": "#27272a", "fg": "#71717a", "text": "● 加载中..."},
    "ready":      {"bg": "#0c4a6e", "fg": "#7dd3fc", "text": "● 就绪"},
    "idle":       {"bg": "#1e293b", "fg": "#64748b", "text": "● 等待唤醒词"},
    "recording":  {"bg": "#064e3b", "fg": "#6ee7b7", "text": "● 录音中"},
    "active":     {"bg": "#064e3b", "fg": "#6ee7b7", "text": "● 录音中"},
    "processing": {"bg": "#312e81", "fg": "#a5b4fc", "text": "● 处理中..."},
    "saving":     {"bg": "#27272a", "fg": "#a1a1aa", "text": "● 保存中..."},
    "switching":  {"bg": "#27272a", "fg": "#a1a1aa", "text": "● 切换中..."},
    "error":      {"bg": "#78350f", "fg": "#fcd34d", "text": "● 错误"},
}

MAX_WIDTH_RATIO = 0.5
TASKBAR_MARGIN = 56
PAD_X = 24
PAD_Y = 10
CORNER_RADIUS = 16


class OverlayWindow:
    def __init__(self, port: int = UDP_PORT):
        self._port = port
        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.88)
        # 透明色作为窗口背景，用于圆角效果
        self._transparent = "#010101"
        self._root.configure(bg=self._transparent)
        self._root.attributes("-transparentcolor", self._transparent)

        self._font = tkfont.Font(family="Microsoft YaHei UI", size=11, weight="bold")
        self._line_h = self._font.metrics("linespace")

        self._screen_w = self._root.winfo_screenwidth()
        self._screen_h = self._root.winfo_screenheight()
        self._max_w = int(self._screen_w * MAX_WIDTH_RATIO)

        self._canvas_h = self._line_h + PAD_Y * 2 + 4
        self._canvas = tk.Canvas(
            self._root,
            height=self._canvas_h,
            bg=self._transparent,
            highlightthickness=0,
            bd=0,
        )
        self._canvas.pack(fill=tk.X)

        # 圆角矩形背景
        self._bg_id = None
        # 居中文本
        self._text_id = self._canvas.create_text(
            0, self._canvas_h // 2,
            text="  Shokz Type  ",
            font=self._font,
            fill="white",
            anchor="center",
        )

        self._root.update_idletasks()
        self._apply({"status": "loading"})

        # UDP 接收线程
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", self._port))
        self._sock.settimeout(0.5)
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.after(200, self._check_updates)
        self._root.after(1000, self._ensure_topmost)

        self._pending = None

    def _recv_loop(self):
        while self._running:
            try:
                data, _ = self._sock.recvfrom(8192)
                msg = json.loads(data.decode("utf-8"))
                self._pending = msg
            except socket.timeout:
                continue
            except Exception:
                continue

    def _check_updates(self):
        if self._pending:
            msg = self._pending
            self._pending = None
            self._apply(msg)
        if self._running:
            self._root.after(100, self._check_updates)

    def _reposition(self):
        self._root.update_idletasks()
        w = self._root.winfo_width()
        h = self._root.winfo_height()
        x = (self._screen_w - w) // 2
        y = self._screen_h - h - TASKBAR_MARGIN
        self._root.geometry(f"+{x}+{y}")

    def _draw_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        """在 Canvas 上画圆角矩形。"""
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1, x2, y1 + r,
            x2, y2 - r,
            x2, y2, x2 - r, y2,
            x1 + r, y2,
            x1, y2, x1, y2 - r,
            x1, y1 + r,
            x1, y1, x1 + r, y1,
        ]
        return self._canvas.create_polygon(points, smooth=True, **kwargs)

    def _apply(self, msg: dict):
        status = msg.get("status", "loading")
        text = msg.get("text")
        style = STYLES.get(status, STYLES["loading"])

        display = text or style["text"]
        bg = style["bg"]
        fg = style["fg"]

        # 计算文本宽度
        text_w = self._font.measure(display) + PAD_X * 2
        win_w = min(text_w, self._max_w)
        win_w = max(win_w, 140)

        self._canvas.config(width=win_w, bg=self._transparent)
        self._root.configure(bg=self._transparent)

        # 重绘圆角背景
        if self._bg_id:
            self._canvas.delete(self._bg_id)
        self._bg_id = self._draw_rounded_rect(
            0, 0, win_w, self._canvas_h, CORNER_RADIUS,
            fill=bg, outline=bg,
        )
        self._canvas.tag_lower(self._bg_id)

        # 文本居中
        if text_w > self._max_w:
            # 超长文本：右对齐显示最新内容
            self._canvas.coords(self._text_id, win_w - PAD_X, self._canvas_h // 2)
            self._canvas.itemconfig(self._text_id, text=display, fill=fg, anchor="e")
        else:
            # 正常：居中
            self._canvas.coords(self._text_id, win_w // 2, self._canvas_h // 2)
            self._canvas.itemconfig(self._text_id, text=display, fill=fg, anchor="center")

        self._root.geometry(f"{win_w}x{self._canvas_h}")
        self._reposition()

    def _ensure_topmost(self):
        if not self._running:
            return
        try:
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            hwnd = self._root.winfo_id()
            parent = ctypes.windll.user32.GetParent(hwnd)
            if parent:
                hwnd = parent
            ctypes.windll.user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE
            )
        except Exception:
            pass
        self._root.after(5000, self._ensure_topmost)

    def _on_close(self):
        self._running = False
        self._sock.close()
        self._root.destroy()

    def run(self):
        self._root.mainloop()


if __name__ == "__main__":
    port = UDP_PORT
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        port = int(sys.argv[idx + 1])
    overlay = OverlayWindow(port=port)
    overlay.run()
