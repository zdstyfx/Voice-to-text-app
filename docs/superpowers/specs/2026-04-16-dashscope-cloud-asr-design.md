# DashScope Cloud ASR Integration Design

## Summary

Integrate DashScope (Alibaba Cloud) Paraformer cloud ASR into vocotype as an alternative to the local FunASR ONNX engine. Users switch between local and cloud backends via a config field. Cloud ASR uses the same DashScope API key the user already has for Qwen.

## Motivation

- Local Paraformer-large ONNX is limited by CPU compute; cloud version uses larger models with higher accuracy
- Better hotword/domain adaptation in cloud
- User already has a DashScope API key (`sk-` format)

## Scope

**In scope:**
- DashScope Paraformer cloud ASR integration (file recognition mode)
- Config-driven backend switching (`asr.backend: "local" | "cloud"`)
- New `app/cloud_asr.py` module wrapping DashScope Recognition SDK
- Both F2 manual recording and VAD auto-detect modes

**Out of scope:**
- Cloud speaker recognition (DashScope has no speaker verification API)
- Real-time streaming mode (reserved for future iteration after file mode is validated)
- Auto-fallback from cloud to local on network failure

## Configuration

Add to `DEFAULT_CONFIG` in `app/config.py`:

```python
"asr": {
    "backend": "local",          # "local" | "cloud"
    # ... existing fields unchanged ...
},
"cloud_asr": {
    "provider": "dashscope",
    "api_key": "",               # sk-xxx, fallback to env DASHSCOPE_API_KEY
    "model": "paraformer-realtime-v2",
    "format": "pcm",
    "sample_rate": 16000,
    "disfluency_removal": False,
},
```

### API Key resolution order

1. `config["cloud_asr"]["api_key"]` (config.json)
2. Environment variable `DASHSCOPE_API_KEY`
3. If neither: raise error at startup with clear message

## Architecture

### New module: `app/cloud_asr.py`

```
class CloudASR:
    __init__(config: dict)
        - Read cloud_asr config section
        - Resolve API key (config -> env var -> error)
        - Store parameters; do NOT create Recognition instance yet

    transcribe_file(wav_path: str) -> dict
        - Create Recognition instance with RecognitionCallback
        - Call Recognition.call(file=wav_path) synchronously
        - Collect sentences from on_event callbacks
        - Return unified result dict:
          {"success": bool, "text": str, "raw_text": str,
           "confidence": float, "duration": float, "error": str|None}

    # Future: streaming methods
    start_stream() -> None
    send_frame(pcm_bytes: bytes) -> None
    stop_stream() -> dict
```

Key design decisions:
- **Unified return format**: Same dict structure as `FunASRServer.transcribe_audio()` so callers need no changes
- **Callback-to-sync bridge**: `RecognitionCallback.on_event/on_complete` collect results into a list; `on_complete` signals a `threading.Event`; `transcribe_file` waits on that event
- **Error wrapping**: Network timeouts, API errors wrapped as `{"success": False, "error": "..."}`
- **No persistent connection**: Each `transcribe_file` call creates a fresh Recognition instance (stateless, simple)

### Integration points

#### `app/transcribe.py` (F2 manual recording)

In `TranscriptionWorker.__init__`:
- Read `config["asr"]["backend"]`
- If `"local"`: initialize `FunASRServer` as before
- If `"cloud"`: initialize `CloudASR` instead, skip FunASR model loading

In `_transcribe_once(samples)`:
- If `"local"`: `self.fun_server.transcribe_audio(path)` (unchanged)
- If `"cloud"`: `self.cloud_asr.transcribe_file(path)`
- Rest of the method (result construction, on_result callback) unchanged

#### `app/vad_worker.py` (VAD continuous listening)

Same pattern as transcribe.py:
- `__init__`: conditionally init FunASRServer or CloudASR based on backend
- `_transcribe_once`: route to local or cloud transcription
- Everything else unchanged (VAD, speaker, KWS)

### What does NOT change

- `TranscriptionResult` dataclass
- `on_result` callback interface
- Speaker recognition (CAM++ local)
- VAD detection (FireRedVAD)
- KWS detection (sherpa-onnx)
- Audio capture / audio source abstraction
- Output / keyboard simulation

## Startup behavior

| backend | FunASR loaded | CloudASR loaded | API key needed |
|---------|--------------|-----------------|----------------|
| `local` | Yes | No | No |
| `cloud` | No | Yes | Yes |

Cloud mode skips FunASR model loading entirely, resulting in faster startup and lower memory usage.

## Dependencies

- `dashscope` >= 1.25.0 (already installed, v1.25.17)
- No new system dependencies

## API Key security

- Never hardcoded or committed to git
- `config.json` is already in `.gitignore`
- Environment variable as alternative

## Future work (not in this iteration)

- **VAD streaming mode**: In `_listen_loop`, call `start_stream()` at speech start, `send_frame()` per audio frame, `stop_stream()` at speech end. Lower latency than file mode.
- **Auto-fallback**: Default cloud, fallback to local on network error
- **Cloud speaker recognition**: If DashScope adds speaker verification API
- **Other providers**: Azure Speech, Whisper API via same config pattern (`cloud_asr.provider`)

## File changes summary

| File | Change |
|------|--------|
| `app/cloud_asr.py` | **New** — CloudASR class |
| `app/config.py` | Add `asr.backend` and `cloud_asr` config section |
| `app/transcribe.py` | Conditional init + routing in `_transcribe_once` |
| `app/vad_worker.py` | Conditional init + routing in `_transcribe_once` |
