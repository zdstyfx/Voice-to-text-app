"""Shokz Type Web service entry point.

Usage: python -m shokztype [--port 8000]
"""

import argparse
import logging


def main():
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
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
