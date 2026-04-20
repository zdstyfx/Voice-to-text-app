"""FireRedVAD streaming wrapper with frame adaptation for vocotype."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import numpy as np

from fireredvad import FireRedStreamVad, FireRedStreamVadConfig
from fireredvad.core.constants import FRAME_LENGTH_SAMPLE, FRAME_SHIFT_SAMPLE

logger = logging.getLogger(__name__)


def _resolve_model_dir(configured_dir: str) -> str:
    """Resolve the Stream-VAD model directory.

    Priority:
      1. Non-empty *configured_dir* that exists on disk.
      2. Auto-detect relative to the fireredvad package install location.
    """
    if configured_dir and os.path.isdir(configured_dir):
        return configured_dir

    import fireredvad as _pkg

    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(_pkg.__file__)))
    candidate = os.path.join(pkg_root, "pretrained_models", "FireRedVAD", "Stream-VAD")
    if os.path.isdir(candidate):
        return candidate

    raise FileNotFoundError(
        f"FireRedVAD Stream-VAD model directory not found. "
        f"Tried configured path '{configured_dir}' and auto-detected '{candidate}'. "
        f"Please set vad.model_dir in your config to a valid directory."
    )


class VadProcessor:
    """Wraps FireRedStreamVad with frame adaptation.

    Vocotype AudioCapture produces 320-sample frames (16kHz * 20ms).
    FireRedVAD needs 400-sample windows with 160-sample stride.
    This class buffers incoming frames and yields VAD results at the
    correct cadence.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        vad_cfg = config.get("vad", {})
        model_dir = _resolve_model_dir(vad_cfg.get("model_dir", ""))

        stream_config = FireRedStreamVadConfig(
            use_gpu=vad_cfg.get("use_gpu", False),
            speech_threshold=vad_cfg.get("speech_threshold", 0.4),
            smooth_window_size=vad_cfg.get("smooth_window_size", 5),
            min_speech_frame=vad_cfg.get("min_speech_frame", 8),
            max_speech_frame=vad_cfg.get("max_speech_frame", 2000),
            min_silence_frame=vad_cfg.get("min_silence_frame", 20),
            pad_start_frame=vad_cfg.get("pad_start_frame", 5),
            chunk_max_frame=vad_cfg.get("chunk_max_frame", 30000),
        )

        logger.info("Loading FireRedStreamVad from %s", model_dir)
        self._stream_vad = FireRedStreamVad.from_pretrained(model_dir, stream_config)
        self._sample_buffer = np.array([], dtype=np.int16)
        logger.info("FireRedStreamVad loaded successfully")

    def process_frame(self, frame: np.ndarray) -> List:
        """Accept a mic frame (typically 320 samples) and return VAD results.

        Returns a list of ``StreamVadFrameResult`` objects (0, 1, or 2 per
        mic frame depending on buffer state).
        """
        self._sample_buffer = np.concatenate([self._sample_buffer, frame])

        results = []
        while len(self._sample_buffer) >= FRAME_LENGTH_SAMPLE:
            window = self._sample_buffer[:FRAME_LENGTH_SAMPLE]
            result = self._stream_vad.detect_frame(window)
            results.append(result)
            self._sample_buffer = self._sample_buffer[FRAME_SHIFT_SAMPLE:]

        return results

    def reset(self) -> None:
        """Reset VAD state for a new detection cycle."""
        self._stream_vad.reset()
        self._sample_buffer = np.array([], dtype=np.int16)
