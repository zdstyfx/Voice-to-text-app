# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Shokz Type** (package name `shokztype`) is a Chinese voice-to-text application. It captures audio, runs speech recognition (local FunASR or cloud DashScope/VolcEngine), and types the result into the active window. The primary interface is a FastAPI web server with a browser-based SPA.

## Running

```bash
pip install -r requirements.txt
cp config.json.example config.json   # set cloud_asr.api_key if using cloud ASR

python -m shokztype                  # web server (default localhost:8000)
python -m shokztype --port 9000      # custom port
shokztype-cli                        # interactive CLI mode (menu-driven)
shokztype-cli --web                  # NiceGUI desktop UI on port 8080
```

## Tests

```bash
python -m pytest tests/ -v
python -m pytest tests/test_speaker_db.py -v          # single file
python -m pytest tests/test_speaker_db.py::test_name -v  # single test
```

`tests/conftest.py` mocks `torch`, `torchaudio`, and `fireredvad` so tests run without GPU/model dependencies.

## Architecture

### Three interfaces, one core

```
shokztype/
├── core/          # Audio pipeline: capture, VAD, ASR, speaker, KWS, output
├── web/           # FastAPI web service (primary interface)
│   ├── server.py          # App factory + lifespan
│   ├── static/index.html  # Vanilla JS SPA
│   ├── routers/           # 8 REST/SSE routers
│   └── services/          # Pipeline orchestration, transcribers, wakeup modules
├── desktop/       # NiceGUI desktop UI (alternative, via `shokztype-cli --web`)
├── __main__.py    # Entry point for `python -m shokztype` (web mode)
└── cli.py         # Entry point for `shokztype-cli` (interactive CLI)
```

All three interfaces share `core/` but wire it differently:
- **Web** (`__main__.py`): Uses EventBus-driven pipeline in `web/services/recording_pipeline.py`
- **CLI** (`cli.py`): Wires core components directly with callbacks
- **Desktop** (`desktop/`): NiceGUI pages with shared `AppState` singleton

### EventBus architecture (web mode)

The web service uses a publish-subscribe `EventBus` (`web/services/event_bus.py`) to decouple components. The pipeline in `recording_pipeline.py` assembles modules and connects them via bus events:

```
Wakeup Module ──emit("start"/"stop")──► Transcriber Module
     │                                       │
     │                                  emit("partial"/"result"/"done")
     │                                       │
     └──── EventBus ◄────────────────────────┘
                │
          _on_bus_result() → text_pipeline (LLM) → type_text()
          _on_bus_state()  → overlay UDP + SSE to browser
```

**Wakeup modules** (mutually exclusive):
- `HotkeyWakeup` — keyboard shortcut toggles recording
- `VadKwsWakeup` — VAD + keyword spotter, state machine: IDLE → ACTIVE → LOCKED → IDLE

**Transcriber modules** (mutually exclusive):
- `BatchTranscriber` — records audio, sends to FunASR after stop
- `StreamTranscriber` — WebSocket streaming to cloud ASR (DashScope/VolcEngine)

**Optional frame filter**: `SpeakerGate` inserts between wakeup and transcriber to filter by voiceprint.

### Pipeline lifecycle

`init_worker()` in `recording_pipeline.py` **must be called in the main thread** (Python `signal` module constraint). `__main__.py` calls it before `uvicorn.run()`. The `_assemble()` function wires modules based on config; `restart_pipeline()` tears down and reassembles on config changes.

### Config system

Two layers, both reading from `config.json`:
- `core/config.py` — `DEFAULT_CONFIG` with audio/VAD/ASR/speaker/KWS defaults
- `web/web_config.py` — extends with LLM/prompt/wakeup/voiceprint fields

`_merge_dict()` does recursive deep merge; user config overrides only keys it sets. `update_config()` persists changes back to `config.json` and emits `config_changed` on the bus.

### ASR backends

Three providers, unified return format `{success, text, raw_text, confidence, duration}`:
- **Local FunASR** (`funasr_server.py`) — ONNX Paraformer, auto-downloads ~500MB from ModelScope
- **DashScope** (`cloud_asr.py`) — Alibaba streaming API
- **VolcEngine** (`volcengine_asr.py`) — ByteDance Seed ASR, binary WebSocket protocol

`cloud_asr_factory.py` selects the implementation based on `asr.backend` and `cloud_asr.provider` config fields.

FunASR is loaded once and reused via monkey-patching (`_install_funasr_reuse_patch` replaces `FunASRServer` class with a wrapper that returns the cached instance).

### Path resolution

`shokztype.PROJECT_ROOT` = repo root (dirname of package). `shokztype.APP_DIR` = same in dev, but `dirname(sys.executable)` when frozen with PyInstaller. All config/log/model paths resolve relative to `APP_DIR`.

## Key Conventions

- **Windows-specific code**: `keyboard` lib, `winsound.Beep`, ctypes `SendInput` in `output.py` — all Windows-dependent. The `keyboard` library requires root/admin on non-Windows.
- **Model auto-download**: First run downloads FunASR (~500MB), CAM++ (~27MB), FireRedVAD (~10MB) from ModelScope. Set `MODELSCOPE_CACHE` to control cache location.
- **KWS tokens**: `keywords.txt` is token-indexed (not plain text). Use the web UI "add keyword" API or `shokztype-kws` CLI to convert text to tokens.
- **Audio format**: 16kHz 16-bit mono PCM throughout the pipeline.
- **Chinese UI/logs**: User-facing strings and log messages are in Chinese.
