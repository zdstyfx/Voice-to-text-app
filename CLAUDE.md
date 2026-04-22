# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Shokz Type** is a Chinese voice-to-text application for Windows. It captures audio, runs speech recognition, and types the result into the active window. The app runs as a FastAPI web server with a browser-based UI.

Single entry point: `python -m shokztype` starts the FastAPI server and serves `static/index.html`.

## Running

```bash
pip install -r requirements.txt
cp config.json.example config.json   # set cloud_asr.api_key if using DashScope

python -m shokztype                  # start web server (default port 8000)
python -m shokztype --port 9000      # custom port
```

## Tests

```bash
python -m pytest tests/ -v
python -m pytest tests/test_speaker_db.py -v          # single file
python -m pytest tests/test_speaker_db.py::test_name -v  # single test
```

`tests/conftest.py` mocks `torch`, `torchaudio`, and `fireredvad` so tests run without GPU/model dependencies.

## Package Structure

```
shokztype/                  # Top-level Python package
├── __init__.py             # __version__, PROJECT_ROOT constant
├── __main__.py             # Entry point: init_worker() + uvicorn
├── core/                   # Audio pipeline (was: app/)
│   └── ...                 # 18 modules (see below)
└── web/                    # FastAPI web service (was: web/)
    ├── server.py           # App factory, lifespan, static file serving
    ├── web_config.py       # Extends core config with LLM/prompt/wakeup fields
    ├── models.py           # Pydantic request/response models
    ├── static/index.html   # Browser UI (vanilla JS SPA)
    ├── routers/            # 8 API routers
    └── services/           # 6 service modules
```

### `shokztype/core/` — Audio pipeline

Public API exported via `core/__init__.py`: `load_config`, `AudioCapture`, `TranscriptionWorker`, `type_text`.

Key modules:
- **config.py** — `DEFAULT_CONFIG` dict with all settings; `load_config()` deep-merges `config.json` on top
- **audio_source.py** — Abstract `AudioSource` base class
- **audio_capture.py** — `AudioCapture` — sounddevice microphone (16kHz 16-bit PCM)
- **funasr_server.py** — Local ASR via FunASR ONNX (Paraformer, ~500MB auto-download from ModelScope)
- **cloud_asr.py** — Cloud ASR via DashScope streaming API (needs `DASHSCOPE_API_KEY` or config)
- **vad.py** — FireRedVAD wrapper for speech/silence classification
- **vad_worker.py** — `VadTranscriptionWorker` — continuous VAD-triggered recording + ASR
- **kws.py** — Sherpa-ONNX keyword spotter for wake-word activation
- **speaker.py** — CAM++ speaker embeddings (~27MB auto-download)
- **speaker_db.py** — JSON-based speaker database
- **speaker_cluster.py** — Hierarchical clustering for diarization
- **transcribe.py** — `TranscriptionWorker` — hotkey toggle record/transcribe
- **output.py** — `type_text()` — types text into active window (Windows keyboard + clipboard fallback)
- **command_dispatcher.py** — Voice command registration and matching framework

### `shokztype/web/` — FastAPI service

- **server.py** — App factory with lifespan. Serves `static/index.html` at `/`.
- **web_config.py** — Extends `core.config.DEFAULT_CONFIG` with LLM/prompt/wakeup/voiceprint fields. Has its own `load_config()`/`get_config()`/`update_config()` that persist to `config.json`.
- **routers/** — `health`, `modes`, `settings`, `devices`, `process`, `voiceprint`, `wakeup`, `recording`
- **services/recording_pipeline.py** — Main orchestration. **`init_worker()` must be called in the main thread** (Python signal module constraint); `__main__.py` calls it at module level before `uvicorn.run()`.
- **services/text_pipeline.py** — Routes text through LLM for translate/polish modes
- **services/llm_client.py** — Generic OpenAI-compatible LLM client

## Configuration

`config.json` extends `config.json.example`. Sections: `hotkeys`, `audio`, `vad`, `asr`, `cloud_asr`, `output`, `speaker`, `kws`, `logging`, plus web-specific: `llm`, `prompts`, `voiceprint`, `wakeup`.

## Key Design Notes

- **Project root**: `shokztype.PROJECT_ROOT` — canonical constant used by all path resolution instead of fragile `dirname(__file__)` chains.
- **ASR return format**: Both `funasr_server.py` and `cloud_asr.py` return `{success, text, raw_text, confidence, duration}` — interchangeable.
- **Config merging**: `_merge_dict()` does recursive dict merge. User `config.json` overrides only the keys it sets.
- **Two config layers**: `core/config.py` has base defaults; `web/web_config.py` extends with web-specific fields. Both read from `config.json`.
- **Model auto-download**: First run downloads FunASR (~500MB), CAM++ (~27MB), FireRedVAD (~10MB) from ModelScope. Set `MODELSCOPE_CACHE` to control cache location.
- **Windows-specific**: `keyboard` lib, `winsound.Beep`, ctypes `SendInput` — all Windows-dependent.
- **KWS tokens**: `keywords.txt` is token-indexed. Use the web UI "add keyword" API to convert text to tokens.
- **GPU**: Default CPU. For CUDA: `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121` and set `FUNASR_DEVICE=cuda:0`.
