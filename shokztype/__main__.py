"""Shokz Type Web service entry point.

Usage:
    python -m shokztype                # 桌面窗口模式（默认）
    python -m shokztype --no-window    # 仅启动 HTTP 服务，不弹窗口
    python -m shokztype --port 9000    # 自定义端口
"""

import argparse
import atexit
import logging
import threading
import time
from urllib.request import urlopen
from urllib.error import URLError


def _wait_for_server(host: str, port: int, timeout: float = 30):
    """轮询 /api/health 直到服务就绪。"""
    url = f"http://{host}:{port}/api/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urlopen(url, timeout=2)
            return
        except (URLError, OSError):
            time.sleep(0.2)
    raise TimeoutError(f"服务未在 {timeout}s 内就绪: {url}")


def _get_icon_path():
    """定位韶音图标文件。"""
    import sys
    from pathlib import Path

    base_dirs = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            base_dirs.append(Path(meipass))

        exe_dir = Path(sys.executable).resolve().parent
        base_dirs.extend([exe_dir, exe_dir / "_internal"])
    else:
        base_dirs.append(Path(__file__).resolve().parents[1])

    candidates = [
        base / "shokztype" / "assets" / "shokztype.ico"
        for base in base_dirs
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    searched = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"未找到应用图标 shokztype.ico，已检查: {searched}")


def _set_windows_app_user_model_id():
    """设置 Windows 任务栏应用身份，避免使用 Python/WebView 默认图标。"""
    import sys

    if sys.platform != "win32":
        return

    try:
        import ctypes

        app_id = "Shokz.ShokzType"
        shell32 = ctypes.windll.shell32
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        logging.getLogger(__name__).debug(
            "设置 Windows AppUserModelID 失败", exc_info=True
        )


def _load_icon_image(icon_path: str):
    from PIL import Image
    with Image.open(icon_path) as image:
        return image.copy()


def _run_with_tray(host: str, port: int):
    """启动 pywebview 窗口 + 系统托盘（Windows）/ Dock 模式（macOS）。"""
    import sys

    _set_windows_app_user_model_id()

    ico_path = _get_icon_path()

    import webview

    really_quit = threading.Event()
    window_ref = [None]

    url = f"http://{host}:{port}"
    window = webview.create_window(
        "Shokz Type", url, width=460, height=720, resizable=True,
    )
    window_ref[0] = window

    if sys.platform == "darwin":
        # macOS: 关闭窗口只隐藏，Cmd+Q / Dock 右键退出才真正退出
        def on_closing():
            if really_quit.is_set():
                return True
            window_ref[0].hide()
            return False

        window.events.closing += on_closing

        def _patch_dock_handlers():
            import objc
            from AppKit import NSApplication

            app = NSApplication.sharedApplication()
            delegate = app.delegate()
            if delegate is None:
                return
            cls = delegate.__class__

            def reopen(self, app, flag):
                if window_ref[0]:
                    window_ref[0].show()
                return True

            sel = b'applicationShouldHandleReopen:hasVisibleWindows:'
            imp = objc.selector(reopen, selector=sel, signature=b'Z@:@Z')
            objc.classAddMethod(cls, sel, imp)

            def should_terminate(self, sender):
                really_quit.set()
                from shokztype.web.services.recording_pipeline import stop_pipeline
                stop_pipeline()
                return 1  # NSTerminateNow

            sel_term = b'applicationShouldTerminate:'
            imp_term = objc.selector(should_terminate, selector=sel_term, signature=b'I@:@')
            objc.classAddMethod(cls, sel_term, imp_term)

        def _deferred_patch():
            _log = logging.getLogger("shokztype.deferred")
            _log.info("deferred_patch 线程已启动")
            import time
            time.sleep(3)
            try:
                from PyObjCTools import AppHelper
                _log.info("正在安装 Dock handler...")
                AppHelper.callAfter(_patch_dock_handlers)
                _log.info("已调度 Dock handler 安装")
            except Exception as e:
                _log.error("deferred patch 失败: %s", e, exc_info=True)

        threading.Thread(target=_deferred_patch, daemon=True).start()

        webview.start(icon=ico_path)

    else:
        # Windows: pystray 系统托盘
        import pystray

        def on_closing():
            if really_quit.is_set():
                return True
            window_ref[0].hide()
            return False

        def tray_show(icon, item):
            window_ref[0].show()

        def tray_quit(icon, item):
            really_quit.set()
            icon.stop()
            window_ref[0].destroy()

        window.events.closing += on_closing

        def _bring_to_front():
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, "Shokz Type")
            if hwnd:
                ctypes.windll.user32.SetForegroundWindow(hwnd)

        def _on_shown():
            threading.Timer(0.5, _bring_to_front).start()

        window.events.shown += _on_shown

        tray_image = _load_icon_image(ico_path)
        menu = pystray.Menu(
            pystray.MenuItem("显示窗口", tray_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出 ShokzType", tray_quit),
        )
        icon = pystray.Icon("ShokzType", tray_image, "Shokz Type", menu)
        icon.run_detached()

        webview.start(icon=ico_path)

        if not really_quit.is_set():
            icon.stop()

    from shokztype.web.services.recording_pipeline import _stop_overlay
    _stop_overlay()


def main():
    import sys, os
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    if "--overlay" in sys.argv:
        port = 0
        if "--port" in sys.argv:
            idx = sys.argv.index("--port")
            port = int(sys.argv[idx + 1])
        from shokztype.web.services.overlay_process import OverlayWindow
        OverlayWindow(port=port).run()
        return

    if "--hotkey-helper" in sys.argv:
        _port, _combo = 0, "f2"
        for i, a in enumerate(sys.argv):
            if a == "--port" and i + 1 < len(sys.argv):
                _port = int(sys.argv[i + 1])
            elif a == "--combo" and i + 1 < len(sys.argv):
                _combo = sys.argv[i + 1]
        if _port:
            from shokztype.core.hotkey_helper import run_helper
            run_helper(_port, _combo)
        return

    import sys as _sys2
    if getattr(_sys2, 'frozen', False):
        from shokztype.core.hotkeys import _runtime_log_dir
        _log_dir = _runtime_log_dir(_sys2.executable)
        _log_dir.mkdir(parents=True, exist_ok=True)
        _log_path = _log_dir / "shokztype.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            filename=_log_path,
            filemode="w",
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    import sys as _sys
    if _sys.platform == "darwin":
        from shokztype.core.platform import ensure_mac_accessibility
        ensure_mac_accessibility()

    from shokztype.web.services.recording_pipeline import init_worker, _stop_overlay
    init_worker()
    atexit.register(_stop_overlay)

    from shokztype.core.hotkeys import PersistentKeyListener
    PersistentKeyListener.get().start()

    import uvicorn
    from shokztype.web.server import create_app

    app = create_app()

    parser = argparse.ArgumentParser(description="Shokz Type")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--overlay", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-window", action="store_true",
                        help="仅启动 HTTP 服务，不弹桌面窗口")
    args = parser.parse_args()

    if args.port == 0:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((args.host, 0))
            args.port = s.getsockname()[1]

    if args.no_window:
        uvicorn.run(app, host=args.host, port=args.port)
        return

    server_thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": args.host, "port": args.port, "log_level": "warning"},
        daemon=True,
    )
    server_thread.start()

    _wait_for_server(args.host, args.port)

    try:
        _run_with_tray(args.host, args.port)
    except Exception:
        import traceback, sys
        if getattr(sys, "frozen", False):
            from shokztype.core.hotkeys import _runtime_log_dir
            crash_dir = _runtime_log_dir(sys.executable)
            crash_dir.mkdir(parents=True, exist_ok=True)
        else:
            from pathlib import Path
            crash_dir = Path(".")
        with open(crash_dir / "crash.log", "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        raise


if __name__ == "__main__":
    main()
