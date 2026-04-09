"""Global state management for the Vocotype Web UI."""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AppState:
    """Centralized application state shared across all web UI components."""

    # Recording state
    is_recording: bool = False
    recording_mode: str = "button"  # "button" | "vad"
    recording_start_time: Optional[float] = None

    # Audio source
    audio_source_type: str = "microphone"  # "microphone" | "esp32" | "device"
    selected_device: Optional[str] = None

    # Transcription
    transcription_results: list = field(default_factory=list)
    transcription_stats: dict = field(default_factory=lambda: {
        "submitted": 0,
        "completed": 0,
        "pending": 0,
        "is_recording": False,
        "is_transcribing": False,
    })

    # ESP32 connection
    esp32_connected: bool = False
    esp32_host: str = "192.168.4.1"
    esp32_port: int = 6000

    # Speaker recognition
    speaker_mode: str = "off"  # "off" | "identify" | "filter" | "enroll"
    speaker_whitelist: list = field(default_factory=list)

    # VAD settings
    vad_threshold: float = 0.4

    # Output settings
    append_newline: bool = False
    dedupe: bool = True

    # Application config (set at startup)
    config: dict = field(default_factory=dict)

    # Worker references (set at runtime, not serialized)
    worker: Optional[Any] = None
    audio: Optional[Any] = None
    speaker_processor: Optional[Any] = None


# Module-level singleton
app_state = AppState()
