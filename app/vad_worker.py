"""VAD auto-detect transcription worker — continuous listening via FireRedVAD."""

from __future__ import annotations

import collections
import logging
import os
import queue
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .audio_capture import AudioCapture
from .audio_source import AudioSource
from .config import ensure_logging_dir, load_config
from .transcribe import TranscriptionResult
from .vad import VadProcessor
from .funasr_server import FunASRServer

logger = logging.getLogger(__name__)


class VadTranscriptionWorker:
    """Continuously listens to audio, uses FireRedVAD to detect speech
    boundaries, and submits detected speech segments for ASR transcription."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        on_result: Optional[Callable[[TranscriptionResult], None]] = None,
        audio_source: Optional[AudioSource] = None,
        speaker_processor: Optional[object] = None,
        speaker_mode: str = "off",
    ) -> None:
        self.config = load_config(config_path)
        self.on_result = on_result
        self.log_dir = ensure_logging_dir(self.config)
        self.last_segment_path: Optional[Path] = None

        audio_cfg = self.config["audio"]
        if audio_source is not None:
            self.audio: AudioSource = audio_source
        else:
            self.audio = AudioCapture(
                sample_rate=audio_cfg["sample_rate"],
                block_ms=audio_cfg["block_ms"],
                device=audio_cfg.get("device"),
            )

        # FunASR
        self.fun_server = FunASRServer()
        init_result = self.fun_server.initialize()
        if not init_result.get("success"):
            raise RuntimeError(f"FunASR initialization failed: {init_result}")

        # Speaker recognition (optional)
        self._speaker_processor = speaker_processor
        self._speaker_mode = speaker_mode

        # Enroll mode state
        spk_cfg = self.config.get("speaker", {})
        self._enroll_target = spk_cfg.get("enroll_target", "")
        self._enroll_samples = spk_cfg.get("enroll_samples", 5)
        self._enroll_count = 0

        # VAD processor
        self._vad = VadProcessor(self.config)

        # Pre-speech rolling buffer
        vad_cfg = self.config.get("vad", {})
        pre_speech_ms = vad_cfg.get("pre_speech_pad_ms", 300)
        block_ms = audio_cfg.get("block_ms", 20)
        self._pre_speech_max_frames = max(1, pre_speech_ms // block_ms)

        # Max speech buffer size safeguard (reuse audio config)
        self._max_session_bytes = audio_cfg.get("max_session_bytes", 20 * 1024 * 1024)
        self._recent_frames: collections.deque = collections.deque(
            maxlen=self._pre_speech_max_frames
        )

        # State
        self._running = threading.Event()
        self._listen_thread: Optional[threading.Thread] = None
        self._in_speech = False
        self._speech_buffer: list[np.ndarray] = []

        # Async transcription queue: items are (audio, speaker_id, speaker_confidence) or None
        self._transcription_queue: "queue.Queue[Optional[tuple]]" = queue.Queue(
            maxsize=10
        )
        self._transcription_thread: Optional[threading.Thread] = None
        self._transcription_running = threading.Event()
        self._transcription_task_count = 0
        self._transcription_completed_count = 0
        self._audio_cfg = audio_cfg

        self._start_transcription_worker()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running.is_set():
            logger.debug("VAD worker already running")
            return
        self._running.set()
        self.audio.start()
        self._listen_thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="VadListenLoop"
        )
        self._listen_thread.start()
        logger.info("VAD auto-detect mode started")

    def stop(self) -> None:
        if not self._running.is_set():
            return
        logger.info("Stopping VAD worker...")
        self._running.clear()
        self.audio.stop()
        self.audio.flush()
        if self._listen_thread and self._listen_thread.is_alive():
            self._listen_thread.join(timeout=3)
        self._listen_thread = None

        # Flush any remaining speech
        if self._in_speech and self._speech_buffer:
            self._submit_speech()

        self._stop_transcription_worker()
        logger.info("VAD worker stopped")

    def cleanup(self) -> None:
        if self._running.is_set():
            self.stop()
        self._speech_buffer.clear()
        self._recent_frames.clear()
        if hasattr(self, "audio"):
            self.audio.stop()

    # ------------------------------------------------------------------
    # Properties (compatible with main.py result handler)
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def is_transcribing(self) -> bool:
        return not self._transcription_queue.empty()

    @property
    def pending_transcriptions(self) -> int:
        return self._transcription_queue.qsize()

    @property
    def transcription_stats(self) -> dict:
        return {
            "submitted": self._transcription_task_count,
            "completed": self._transcription_completed_count,
            "pending": self.pending_transcriptions,
            "is_recording": self._in_speech,
            "is_transcribing": self.is_transcribing,
        }

    # ------------------------------------------------------------------
    # Listen loop
    # ------------------------------------------------------------------

    def _listen_loop(self) -> None:
        queue_obj = self.audio.queue
        while self._running.is_set():
            try:
                frame = queue_obj.get(timeout=0.2)
            except Exception:
                if not self._running.is_set():
                    break
                continue

            if not isinstance(frame, np.ndarray):
                frame = np.frombuffer(frame, dtype=np.int16)

            # Maintain pre-speech rolling buffer
            self._recent_frames.append(frame)

            # Feed VAD
            results = self._vad.process_frame(frame)

            speech_started_this_frame = False
            for result in results:
                if result.is_speech_start and not self._in_speech:
                    self._on_speech_start()
                    speech_started_this_frame = True
                if result.is_speech_end and self._in_speech:
                    self._on_speech_end()

            # Accumulate mic frame while in speech
            # Skip if speech just started this frame (already in buffer via _recent_frames)
            if self._in_speech and not speech_started_this_frame:
                self._speech_buffer.append(frame)

            # Safety: force-submit if speech buffer grows too large
            if self._in_speech:
                buf_bytes = sum(f.nbytes for f in self._speech_buffer)
                if buf_bytes >= self._max_session_bytes:
                    logger.warning("Speech buffer hit size limit (%d bytes), force submitting", buf_bytes)
                    self._in_speech = False
                    self._submit_speech()
                    self._vad.reset()

    def _on_speech_start(self) -> None:
        self._in_speech = True
        # Pre-fill with recent frames before speech was detected
        self._speech_buffer = list(self._recent_frames)
        logger.info("VAD: speech start detected")

    def _on_speech_end(self) -> None:
        self._in_speech = False
        self._submit_speech()
        self._vad.reset()
        logger.info("VAD: speech end detected")

    def _submit_speech(self) -> None:
        if not self._speech_buffer:
            return
        combined = np.concatenate(self._speech_buffer)
        self._speech_buffer.clear()

        duration_s = len(combined) / self._audio_cfg["sample_rate"]
        logger.info("VAD: submitting %.2fs of speech for transcription", duration_s)

        # Enroll mode: store embedding and skip transcription
        if self._speaker_mode == "enroll" and self._speaker_processor:
            if not self._enroll_target:
                logger.error("Enroll mode but no enroll_target configured")
                return
            try:
                embedding = self._speaker_processor.extract_embedding(combined)
                self._speaker_processor.db.enroll(self._enroll_target, embedding)
                self._enroll_count += 1
                logger.info(
                    "Enroll: stored sample %d/%d for '%s'",
                    self._enroll_count,
                    self._enroll_samples,
                    self._enroll_target,
                )
                if self._enroll_count >= self._enroll_samples:
                    logger.info(
                        "Enroll complete: %d samples for '%s'. Switching to filter mode.",
                        self._enroll_count,
                        self._enroll_target,
                    )
                    self._speaker_mode = "filter"
                    self._enroll_count = 0
            except Exception as exc:
                logger.error("Enroll embedding extraction failed: %s", exc)
            return

        # Speaker recognition
        speaker_id: Optional[str] = None
        speaker_confidence: Optional[float] = None

        if self._speaker_processor:
            if self._speaker_mode == "filter":
                ok, sid = self._speaker_processor.should_transcribe(combined)
                if not ok:
                    logger.info("VAD: non-whitelist speaker (%s), skipping", sid)
                    return
                speaker_id = sid
            elif self._speaker_mode == "identify":
                result = self._speaker_processor.identify(combined)
                speaker_id = result.speaker_id
                speaker_confidence = result.confidence

        try:
            self._transcription_queue.put_nowait(
                (combined, speaker_id, speaker_confidence)
            )
            self._transcription_task_count += 1
        except queue.Full:
            logger.error("Transcription queue full, dropping speech segment")

    # ------------------------------------------------------------------
    # Transcription worker (same pattern as TranscriptionWorker)
    # ------------------------------------------------------------------

    def _start_transcription_worker(self) -> None:
        if self._transcription_running.is_set():
            return
        self._transcription_running.set()
        self._transcription_thread = threading.Thread(
            target=self._transcription_worker_loop,
            daemon=True,
            name="VadTranscriptionWorker",
        )
        self._transcription_thread.start()

    def _stop_transcription_worker(self, timeout: float = 5.0) -> None:
        if not self._transcription_running.is_set():
            return
        # Wait for pending tasks
        start_time = time.time()
        while not self._transcription_queue.empty():
            if time.time() - start_time > timeout:
                logger.warning("Transcription queue drain timeout, forcing stop")
                break
            time.sleep(0.1)

        self._transcription_running.clear()
        try:
            self._transcription_queue.put(None, timeout=0.5)
        except queue.Full:
            pass
        if self._transcription_thread and self._transcription_thread.is_alive():
            self._transcription_thread.join(timeout=2.0)
        self._transcription_thread = None

    def _transcription_worker_loop(self) -> None:
        while self._transcription_running.is_set():
            try:
                item = self._transcription_queue.get(timeout=1.0)
                if item is None:
                    break
                try:
                    samples, speaker_id, speaker_confidence = item
                    self._transcribe_once(samples, speaker_id, speaker_confidence)
                    self._transcription_completed_count += 1
                except Exception as exc:
                    logger.error("Transcription error: %s", exc, exc_info=True)
                finally:
                    self._transcription_queue.task_done()
            except queue.Empty:
                continue

    def _transcribe_once(
        self,
        samples: np.ndarray,
        speaker_id: Optional[str] = None,
        speaker_confidence: Optional[float] = None,
    ) -> None:
        tmp_path = self._write_temp_wav(samples)
        start = time.time()
        try:
            asr_result = self.fun_server.transcribe_audio(
                tmp_path, options=self.config.get("asr")
            )
        finally:
            inference_latency = time.time() - start
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        if not asr_result.get("success"):
            result = TranscriptionResult(
                text="",
                raw_text="",
                duration=0.0,
                inference_latency=inference_latency,
                confidence=0.0,
                error=asr_result.get("error", "unknown"),
            )
        else:
            result = TranscriptionResult(
                text=asr_result.get("text", ""),
                raw_text=asr_result.get("raw_text", ""),
                duration=asr_result.get("duration", 0.0),
                inference_latency=inference_latency,
                confidence=asr_result.get("confidence", 0.0),
                speaker=speaker_id,
                speaker_confidence=speaker_confidence,
            )

        if self.on_result:
            try:
                self.on_result(result)
            except Exception as exc:
                logger.error("Result callback error: %s", exc)

    def _write_temp_wav(self, samples: np.ndarray) -> str:
        sample_rate = self._audio_cfg["sample_rate"]

        # Save as recent.wav for debugging
        recent_path = Path(self.log_dir) / "recent.wav"
        os.makedirs(recent_path.parent, exist_ok=True)
        tmp_recent_fd, tmp_recent_path = tempfile.mkstemp(
            prefix="recent_", suffix=".wav", dir=recent_path.parent
        )
        os.close(tmp_recent_fd)
        with wave.open(str(tmp_recent_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(samples.tobytes())
        os.replace(tmp_recent_path, recent_path)
        self.last_segment_path = recent_path

        # Temp file for ASR
        fd, path = tempfile.mkstemp(prefix="asr_vad_", suffix=".wav")
        os.close(fd)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(samples.tobytes())
        return path
