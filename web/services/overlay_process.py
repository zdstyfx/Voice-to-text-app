"""独立进程运行的状态浮窗。通过 UDP 接收状态更新。

启动方式：python -m web.services.overlay_process [--port 9123]
主进程通过 UDP 发送 JSON 消息来更新显示。
"""

import json
import socket
import sys
import threading
import tkinter as tk

UDP_PORT = 9123

# 状态颜色映射
STYLES = {
    "loading":  {"bg": "#555555", "fg": "#ffffff", "text": "ASR 加载中..."},
    "ready":    {"bg": "#166534", "fg": "#ffffff", "text": "就绪 -- 按 F2 录音"},
    "recording":{"bg": "#dc2626", "fg": "#ffffff", "text": "  ● 录音中...  "},
    "processing":{"bg": "#b45309", "fg": "#ffffff", "text": "处理中..."},
    "idle":     {"bg": "#1e40af", "fg": "#ffffff", "text": "IDLE -- 等待唤醒词"},
    "active":   {"bg": "#dc2626", "fg": "#ffffff", "text": "ACTIVE -- 正在听"},
    "error":    {"bg": "#dc2626", "fg": "#ffffff", "text": "错误"},
    "switching":{"bg": "#b45309", "fg": "#ffffff", "text": "切换中..."},
}


class OverlayWindow:
    def __init__(self, port: int = UDP_PORT):
        self._port = port
        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.92)
        self._root.configure(bg="#555")

        self._label = tk.Label(
            self._root,
            text="  Shokz Type  ",
            font=("Microsoft YaHei UI", 11, "bold"),
            fg="white",
            bg="#555",
            padx=14,
            pady=6,
        )
        self._label.pack()

        self._root.update_idletasks()
        x = self._root.winfo_screenwidth() - self._root.winfo_width() - 24
        self._root.geometry(f"+{x}+18")

        # UDP 接收线程
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", self._port))
        self._sock.settimeout(0.5)
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.after(200, self._check_updates)

        self._pending = None

    def _recv_loop(self):
        while self._running:
            try:
                data, _ = self._sock.recvfrom(4096)
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

    def _apply(self, msg: dict):
        status = msg.get("status", "loading")
        text = msg.get("text")
        style = STYLES.get(status, STYLES["loading"])

        display_text = text or style["text"]
        bg = style["bg"]
        fg = style["fg"]

        self._label.config(text=f"  {display_text}  ", bg=bg, fg=fg)
        self._root.configure(bg=bg)
        self._root.update_idletasks()
        x = self._root.winfo_screenwidth() - self._root.winfo_width() - 24
        self._root.geometry(f"+{x}+18")

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
