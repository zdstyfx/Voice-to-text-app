"""Shokz Type Web service entry point.

Usage:
    python -m shokztype                # 桌面窗口模式（默认）
    python -m shokztype --no-window    # 仅启动 HTTP 服务，不弹窗口
    python -m shokztype --port 9000    # 自定义端口
"""

import argparse
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


def main():
    import sys
    if "--overlay" in sys.argv:
        port = 9123
        if "--port" in sys.argv:
            idx = sys.argv.index("--port")
            port = int(sys.argv[idx + 1])
        from shokztype.web.services.overlay_process import OverlayWindow
        OverlayWindow(port=port).run()
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # ASR Worker 必须在主线程初始化（signal 模块限制）
    from shokztype.web.services.recording_pipeline import init_worker
    init_worker()

    import uvicorn
    from shokztype.web.server import create_app

    app = create_app()

    parser = argparse.ArgumentParser(description="Shokz Type")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--overlay", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-window", action="store_true",
                        help="仅启动 HTTP 服务，不弹桌面窗口")
    args = parser.parse_args()

    if args.no_window:
        uvicorn.run(app, host=args.host, port=args.port)
        return

    # 后台线程跑 uvicorn
    server_thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": args.host, "port": args.port, "log_level": "warning"},
        daemon=True,
    )
    server_thread.start()

    _wait_for_server(args.host, args.port)

    # 主线程跑 pywebview 窗口（Windows 上使用 EdgeChromium）
    import webview
    url = f"http://{args.host}:{args.port}"
    webview.create_window("Shokz Type", url, width=460, height=720, resizable=True)
    webview.start()


if __name__ == "__main__":
    main()
