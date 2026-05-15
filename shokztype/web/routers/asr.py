"""ASR local model management endpoints."""

import asyncio
import json
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()

# ── Download state ────────────────────────────────────────────────────────────

_dl_lock = threading.Lock()
_dl_state: dict = {"running": False, "overall_progress": 0, "error": None, "done": False}
_dl_clients: list[asyncio.Queue] = []


def _is_model_cached(model_name: str) -> bool:
    """Check if a FunASR model is already downloaded (no network call)."""
    from shokztype import APP_DIR
    short_name = model_name.split("/")[-1] if "/" in model_name else model_name

    bundled = Path(APP_DIR) / "models" / short_name
    if bundled.exists():
        return True

    cache = Path.home() / ".cache" / "modelscope" / "hub" / "models" / "iic" / short_name
    if cache.exists() and (
        (cache / "model_quant.onnx").exists() or (cache / "model.onnx").exists()
    ):
        return True
    return False


def _broadcast(msg: dict):
    """Push a message to all SSE clients."""
    data = f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
    for q in list(_dl_clients):
        try:
            q.put_nowait(data)
        except Exception:
            pass


def _run_download(loop: asyncio.AbstractEventLoop):
    """Run download_models.main() in a subprocess and relay JSON-line progress."""
    global _dl_state
    with _dl_lock:
        _dl_state = {"running": True, "overall_progress": 0, "error": None, "done": False}

    try:
        # frozen 模式（PyInstaller）下 sys.executable 是打包好的 exe，
        # 不支持 -m 标志；改用 --download-models 特殊参数，由 __main__.py 路由。
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--download-models"]
        else:
            cmd = [sys.executable, "-m", "shokztype.core.download_models"]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                with _dl_lock:
                    if "overall_progress" in msg:
                        _dl_state["overall_progress"] = msg["overall_progress"]
                loop.call_soon_threadsafe(_broadcast, msg)
            except json.JSONDecodeError:
                pass
        proc.wait()
        done_msg = {"stage": "completed", "overall_progress": 100, "success": proc.returncode == 0}
        with _dl_lock:
            _dl_state.update({"running": False, "done": True, "overall_progress": 100})
        loop.call_soon_threadsafe(_broadcast, done_msg)
    except Exception as e:
        err_msg = {"stage": "error", "error": str(e)}
        with _dl_lock:
            _dl_state.update({"running": False, "error": str(e)})
        loop.call_soon_threadsafe(_broadcast, err_msg)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/asr/local/status")
def get_local_status():
    from shokztype.core.funasr_config import get_models_for_download
    models = get_models_for_download()
    model_statuses = [
        {"name": m["type"], "downloaded": _is_model_cached(m["name"])}
        for m in models
    ]
    all_downloaded = all(m["downloaded"] for m in model_statuses)
    with _dl_lock:
        state = dict(_dl_state)
    return {
        "downloaded": all_downloaded,
        "models": model_statuses,
        "downloading": state["running"],
        "overall_progress": state["overall_progress"],
        "error": state["error"],
    }


@router.post("/api/asr/local/download")
async def start_download():
    with _dl_lock:
        if _dl_state["running"]:
            return {"success": False, "message": "下载已在进行中"}

    loop = asyncio.get_running_loop()
    thread = threading.Thread(target=_run_download, args=(loop,), daemon=True)
    thread.start()
    return {"success": True, "message": "下载已开始"}


@router.get("/api/asr/local/download/stream")
async def download_stream():
    q: asyncio.Queue = asyncio.Queue()
    _dl_clients.append(q)

    # Send current state immediately
    with _dl_lock:
        state = dict(_dl_state)
    init_msg = {
        "stage": "downloading" if state["running"] else ("completed" if state["done"] else "idle"),
        "overall_progress": state["overall_progress"],
    }

    async def gen():
        yield f"data: {json.dumps(init_msg, ensure_ascii=False)}\n\n"
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                    yield msg
                    if '"stage": "completed"' in msg or '"stage": "error"' in msg:
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if q in _dl_clients:
                _dl_clients.remove(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
