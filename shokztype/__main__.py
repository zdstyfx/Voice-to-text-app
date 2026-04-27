"""Shokz Type Web service entry point.

Usage: python -m shokztype [--port 8000]
"""

import argparse
import logging


def main():
    # 快速检查：如果是 --overlay 模式，直接启动浮窗，不走主流程
    import sys
    if "--overlay" in sys.argv:
        port = 9123
        if "--port" in sys.argv:
            idx = sys.argv.index("--port")
            port = int(sys.argv[idx + 1])
        from shokztype.web.services.overlay_process import OverlayWindow
        overlay = OverlayWindow(port=port)
        overlay.run()
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

    parser = argparse.ArgumentParser(description="Shokz Type Web Server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--overlay", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
