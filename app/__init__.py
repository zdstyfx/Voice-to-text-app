"""Core runtime package for the speak-keyboard application."""

from .config import DEFAULT_CONFIG, ensure_logging_dir, load_config
from .audio_source import AudioSource
from .audio_capture import AudioCapture
from .udp_audio_source import UDPAudioSource
from .transcribe import TranscriptionWorker, TranscriptionResult
from .hotkeys import HotkeyManager
from .output import type_text

__all__ = [
    "DEFAULT_CONFIG",
    "ensure_logging_dir",
    "load_config",
    "AudioSource",
    "AudioCapture",
    "UDPAudioSource",
    "TranscriptionWorker",
    "TranscriptionResult",
    "HotkeyManager",
    "type_text",
]



