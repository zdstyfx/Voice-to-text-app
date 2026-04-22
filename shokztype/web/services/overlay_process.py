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

UDP_PORT = 9123

# 状态颜色映射
STYLES = {
    "loading":   {"bg": "#555555", "fg": "#ffffff", "text": "加载中..."},
    "ready":     {"bg": "#166534", "fg": "#ffffff", "text": "就绪 -- 按 F2 录音"},
    "recording": {"bg": "#166534", "fg": "#ffffff", "text": "  ● 录音中...  "},
    "processing":{"bg": "#b45309", "fg": "#ffffff", "text": "处理中..."},
    "idle":      {"bg": "#1e40af", "fg": "#ffffff", "text": "IDLE -- 等待唤醒词"},
    "active":    {"bg": "#166534", "fg": "#ffffff", "text": "ACTIVE -- 正在听"},
    "error":     {"bg": "#dc2626", "fg": "#ffffff", "text": "错误"},
    "switching": {"bg": "#b45309", "fg": "#ffffff", "text": "切换中..."},
    "saving":    {"bg": "#b45309", "fg": "#ffffff", "text": "保存中..."},
}

MAX_WIDTH_RATIO = 0.5  # 最大占屏幕宽度的一半
TASKBAR_MARGIN = 56    # 距离屏幕底部的像素（任务栏高度 + 间距）
PAD_X = 18
PAD_Y = 8


class OverlayWindow:
    def __init__(self, port: int = UDP_PORT):
        self._port = port
        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.92)
        self._root.configure(bg="#555")

        self._font = tkfont.Font(family="Microsoft YaHei UI", size=11, weight="bold")
        self._line_h = self._font.metrics("linespace")

        self._screen_w = self._root.winfo_screenwidth()
        self._screen_h = self._root.winfo_screenheight()
        self._max_w = int(self._screen_w * MAX_WIDTH_RATIO)

        # 使用 Canvas 实现文本裁剪 + 右对齐滚动效果
        self._canvas_h = self._line_h + PAD_Y * 2
        self._canvas = tk.Canvas(
            self._root,
            height=self._canvas_h,
            bg="#555",
            highlightthickness=0,
            bd=0,
        )
        self._canvas.pack(fill=tk.X)
        self._text_id = self._canvas.create_text(
            PAD_X, self._canvas_h // 2,
            text="  Shokz Type  ",
            font=self._font,
            fill="white",
            anchor="w",
        )

        self._root.update_idletasks()
        self._reposition()

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
        """将窗口放置在屏幕底部居中，紧贴任务栏上方。"""
        self._root.update_idletasks()
        w = self._root.winfo_width()
        h = self._root.winfo_height()
        x = (self._screen_w - w) // 2
        y = self._screen_h - h - TASKBAR_MARGIN
        self._root.geometry(f"+{x}+{y}")

    def _apply(self, msg: dict):
        status = msg.get("status", "loading")
        text = msg.get("text")
        style = STYLES.get(status, STYLES["loading"])

        display = text or style["text"]
        bg = style["bg"]
        fg = style["fg"]

        # 计算文本自然宽度
        text_w = self._font.measure(display) + PAD_X * 2
        # 窗口宽度：自然宽度或最大宽度，取较小值
        win_w = min(text_w, self._max_w)
        # 至少有个最小宽度
        win_w = max(win_w, 120)

        # 更新画布和文本
        self._canvas.config(width=win_w, bg=bg)
        self._root.configure(bg=bg)

        if text_w > self._max_w:
            # 文本超宽：右对齐，显示最新内容（文本锚点在右侧）
            self._canvas.coords(self._text_id, win_w - PAD_X, self._canvas_h // 2)
            self._canvas.itemconfig(self._text_id, text=display, fill=fg, anchor="e")
        else:
            # 正常：左对齐
            self._canvas.coords(self._text_id, PAD_X, self._canvas_h // 2)
            self._canvas.itemconfig(self._text_id, text=display, fill=fg, anchor="w")

        self._root.geometry(f"{win_w}x{self._canvas_h}")
        self._reposition()

    def _ensure_topmost(self):
        """通过 Windows API 周期性地重新置顶窗口。"""
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
