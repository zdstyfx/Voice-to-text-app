"""Lightweight UI preview server — serves the SPA with mock API responses.

No ML models needed. Run with:
    D:/AnacondaDownload/python.exe run_ui_preview.py
Then open http://localhost:8000
"""
import sys
import types

# Stub heavy ML deps so imports don't fail
for _mod in ['fireredvad', 'funasr_onnx', 'modelscope', 'torch', 'torchaudio',
             'librosa', 'sherpa_onnx', 'addict']:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

from pathlib import Path
import asyncio
import json as _json
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
import uvicorn

STATIC_DIR = Path("shokztype/web/static")

app = FastAPI(title="Shokz Type UI Preview")

# ── Mock API endpoints ──────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/api/modes")
def modes():
    return {
        "modes": [
            {"id": "translate", "name": "翻译", "description": "说中文，打出英文（或其他目标语言）"},
            {"id": "polish",    "name": "润色", "description": "口语转书面语，自动整理措辞"},
            {"id": "transcribe","name": "转写", "description": "说什么打什么，原样输出"},
        ],
        "currentMode": "translate",
    }

@app.post("/api/modes/current")
def set_mode(body: dict):
    return {"success": True}

@app.get("/api/settings")
def get_settings():
    return {
        "asr": {"backend": "volcengine"},
        "cloud_asr": {"api_key": "", "model_id": ""},
        "llm": {"apiBaseUrl": "", "apiKey": "", "model": "gpt-4o-mini",
                "timeoutSeconds": 90, "temperature": 0.2},
        "translateTargetLanguage": "英语",
        "prompts": {"translate": "", "polish": "", "transcribe": ""},
        "currentMode": "translate",
        "audio": {"device": None},
    }

@app.post("/api/settings")
def save_settings(body: dict):
    return {"success": True}

@app.get("/api/devices")
def get_devices():
    return {
        "devices": [
            {"id": "default", "name": "默认麦克风", "is_default": True, "endpoint_id": ""},
            {"id": "dev1",    "name": "USB 麦克风",  "is_default": False, "endpoint_id": ""},
        ]
    }

@app.get("/api/devices/stream")
def device_stream():
    from fastapi.responses import StreamingResponse
    def gen():
        yield "data: {}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/api/voiceprint/profiles")
def vp_profiles():
    return {
        "profiles": [
            {"id": "p1", "name": "我",   "enrollment_complete": True,  "enrollment_steps": 5},
            {"id": "p2", "name": "同事A","enrollment_complete": False, "enrollment_steps": 2},
        ],
        "activeProfiles": ["p1"],
        "sentences": ["请朗读这句话来完成声纹录制。"] * 5,
        "enabled": True,
    }

@app.post("/api/voiceprint/profiles")
async def create_vp(req: Request):
    body = await req.json()
    return {"success": True, "profile": {"id": "new", "name": body.get("name", "")}}

@app.delete("/api/voiceprint/profiles/{pid}")
def delete_vp(pid: str):
    return {"success": True, "voiceprint_disabled": False}

@app.put("/api/voiceprint/active")
def set_active_vp(body: dict):
    return {"success": True, "enabled": bool(body.get("profile_ids"))}

@app.post("/api/voiceprint/profiles/{pid}/enroll")
def enroll_step(pid: str, step: int = 1, duration: int = 5):
    return {"success": True, "message": f"第 {step} 步完成"}

@app.post("/api/voiceprint/enroll/stop")
def enroll_stop():
    return {"success": True}

@app.post("/api/voiceprint/toggle")
def toggle_vp():
    return {"success": True, "enabled": True}

_mock_dl_state = {"downloaded": False}

@app.get("/api/asr/local/status")
def local_asr_status():
    return {
        "downloaded": _mock_dl_state["downloaded"],
        "models": [
            {"name": "asr",  "downloaded": _mock_dl_state["downloaded"]},
            {"name": "vad",  "downloaded": _mock_dl_state["downloaded"]},
            {"name": "punc", "downloaded": _mock_dl_state["downloaded"]},
        ],
        "downloading": False,
        "overall_progress": 100 if _mock_dl_state["downloaded"] else 0,
        "error": None,
    }

@app.post("/api/asr/local/download")
async def start_local_download():
    return {"success": True}

@app.get("/api/asr/local/download/stream")
async def local_download_stream():
    async def gen():
        for i in range(0, 101, 5):
            await asyncio.sleep(0.3)
            yield f"data: {_json.dumps({'stage': 'downloading', 'overall_progress': i})}\n\n"
        _mock_dl_state["downloaded"] = True
        yield f"data: {_json.dumps({'stage': 'completed', 'overall_progress': 100})}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.post("/api/wakeup/record-hotkey")
async def record_hotkey():
    await asyncio.sleep(0.5)
    return {"success": True, "combo": "F2"}

_rec_clients: list[asyncio.Queue] = []
_rec_state = {"status": "ready", "text": None}

async def _rec_broadcast(status: str, text=None):
    _rec_state["status"] = status
    _rec_state["text"] = text
    msg = f"data: {_json.dumps({'event': 'state', 'status': status, 'text': text}, ensure_ascii=False)}\n\n"
    for q in list(_rec_clients):
        try:
            q.put_nowait(msg)
        except Exception:
            pass

async def _rec_broadcast_result(text: str):
    """推送 result 事件，触发前端保存历史记录。"""
    msg = f"data: {_json.dumps({'event': 'result', 'text': text}, ensure_ascii=False)}\n\n"
    for q in list(_rec_clients):
        try:
            q.put_nowait(msg)
        except Exception:
            pass

@app.get("/api/recording/status")
def recording_status():
    return {**_rec_state, "active_device": "default"}

@app.get("/api/recording/stream")
async def recording_stream():
    q: asyncio.Queue = asyncio.Queue()
    _rec_clients.append(q)
    async def gen():
        yield f"data: {_json.dumps({'event': 'state', **_rec_state}, ensure_ascii=False)}\n\n"
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if q in _rec_clients:
                _rec_clients.remove(q)
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.post("/api/recording/restart")
def restart_recording():
    return {"success": True}

@app.post("/api/recording/undo")
def undo_output():
    return {"success": True, "chars": 10, "message": "mock undo"}

@app.post("/api/recording/_demo")
async def demo_recording():
    """模拟一次完整录音周期（仅用于 UI 预览测试）。"""
    async def _run():
        await _rec_broadcast("recording")
        await asyncio.sleep(2)
        await _rec_broadcast("recording", "今天天气不错，适合出门走走。")
        await asyncio.sleep(1.5)
        await _rec_broadcast("processing", "今天天气不错，适合出门走走。")
        await asyncio.sleep(1)
        result_text = "Today the weather is nice, perfect for a walk outside."
        await _rec_broadcast_result(result_text)
        await _rec_broadcast("ready")
    asyncio.create_task(_run())
    return {"success": True}

@app.get("/api/wakeup")
def get_wakeup():
    return {
        "methods": ["hotkey"],
        "hotkey_combo": "F9",
        "start_keywords": ["你好小韶", "开始识别"],
        "end_keywords": ["退出", "取消", "再见"],
    }

@app.post("/api/wakeup")
def save_wakeup(body: dict):
    return {"success": True}

@app.post("/api/wakeup/add-start-keyword")
async def add_kw():
    return {"success": True}

@app.delete("/api/wakeup/start-keywords/{name}")
def del_kw(name: str):
    return {"success": True}

# ── Static files + SPA fallback ─────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")

# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("UI Preview: http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
