"""FastAPI 应用工厂。"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from shokztype.web.web_config import load_config, get_config
from shokztype.web.routers import health, modes, settings, devices, process, voiceprint, wakeup, recording, asr
from shokztype.web.services import device_monitor, voiceprint_manager
from shokztype.web.services import recording_pipeline

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    _log = logging.getLogger(__name__)

    _log.info("[lifespan] 加载配置...")
    config = load_config()

    _log.info("[lifespan] 同步 keywords.txt 与 config...")
    from shokztype.web.routers.wakeup import sync_keywords_on_startup
    sync_keywords_on_startup()

    _log.info("[lifespan] 绑定事件循环...")
    recording_pipeline.start_pipeline(asyncio.get_event_loop())

    _log.info("[lifespan] 启动设备监控 (COM)...")
    device_monitor.start_listening(asyncio.get_event_loop())

    _log.info("[lifespan] 启动完成")
    yield

    recording_pipeline.stop_pipeline()
    device_monitor.stop_listening()


def create_app() -> FastAPI:
    app = FastAPI(title="Shokz Type", version="0.1.0", lifespan=lifespan)

    app.include_router(health.router)
    app.include_router(modes.router)
    app.include_router(settings.router)
    app.include_router(devices.router)
    app.include_router(process.router)
    app.include_router(voiceprint.router)
    app.include_router(wakeup.router)
    app.include_router(recording.router)
    app.include_router(asr.router)

    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app
