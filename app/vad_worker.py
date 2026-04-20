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
        speaker_cluster: Optional[object] = None,
        kws_enabled: bool = False,
        on_partial: Optional[Callable[[str], None]] = None,
        on_sentence: Optional[Callable[[str], None]] = None,
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

        # ASR 引擎（本地或云端）
        self._asr_backend = self.config.get("asr", {}).get("backend", "local")
        self.fun_server = None
        self.cloud_asr = None

        # 云端流式回调
        self._on_partial = on_partial
        self._on_sentence = on_sentence
        self._cloud_streaming = self._asr_backend == "cloud" and on_partial is not None

        if self._asr_backend == "cloud":
            from .cloud_asr import CloudASR
            self.cloud_asr = CloudASR(self.config)
        else:
            self.fun_server = FunASRServer()
            init_result = self.fun_server.initialize()
            if not init_result.get("success"):
                raise RuntimeError(f"FunASR initialization failed: {init_result}")

        # Speaker recognition (optional)
        self._speaker_processor = speaker_processor
        self._speaker_mode = speaker_mode

        self._speaker_cluster = speaker_cluster

        # VAD processor
        self._vad = VadProcessor(self.config)

        # Pre-speech rolling buffer
        # KWS mode needs ~2s for speaker verification; normal VAD only needs 300ms
        vad_cfg = self.config.get("vad", {})
        pre_speech_ms = 2000 if kws_enabled else vad_cfg.get("pre_speech_pad_ms", 300)
        block_ms = audio_cfg.get("block_ms", 20)
        self._pre_speech_max_frames = max(1, pre_speech_ms // block_ms)

        # Max speech buffer size safeguard (reuse audio config)
        self._max_session_bytes = audio_cfg.get("max_session_bytes", 20 * 1024 * 1024)
        self._recent_frames: collections.deque = collections.deque(
            maxlen=self._pre_speech_max_frames
        )

        # Merge gap: after speech_end, wait this long before submitting to ASR.
        # If new speech starts within the gap, keep accumulating.
        self._merge_gap_s = vad_cfg.get("merge_gap_ms", 800) / 1000.0
        self._pending_submit_time: Optional[float] = None

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

        # KWS state machine
        self._kws_enabled = kws_enabled
        self._kws_state = "idle"  # "idle" | "active"
        self._active_since: float = 0.0
        self._kws_detector = None
        self._command_dispatcher = None
        self._kws_active_timeout = 30
        self._kws_unmatched = "type"
        self._kws_continuous = False  # "开始录音"后进入持续转写，不超时

        if self._kws_enabled:
            from .kws import KwsDetector
            from .command_dispatcher import CommandDispatcher
            self._kws_detector = KwsDetector(self.config)
            self._command_dispatcher = CommandDispatcher()
            self._kws_active_timeout = self.config.get("kws", {}).get("active_timeout_s", 30)
            self._kws_unmatched = self.config.get("kws", {}).get("unmatched_action", "type")
            logger.info("KWS voice assistant mode enabled")

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

        # 云端流式模式：建立 WebSocket 连接（KWS 模式下延迟到 active 态建连）
        if self._cloud_streaming and not self._kws_enabled:
            try:
                self.cloud_asr.start_streaming(self._on_partial, self._on_sentence)
            except Exception as e:
                logger.error("云端流式 ASR 启动失败: %s", e)
                self._running.clear()
                self.audio.stop()
                raise

        self._listen_thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="VadListenLoop"
        )
        self._listen_thread.start()
        logger.info("VAD auto-detect mode started (streaming=%s)", self._cloud_streaming)

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

        # 云端流式模式：关闭 WebSocket 连接
        if self._cloud_streaming and self.cloud_asr:
            try:
                self.cloud_asr.stop_streaming()
            except Exception as e:
                logger.warning("关闭云端流式 ASR 异常: %s", e)

        # Flush any remaining or pending speech
        if self._speech_buffer:
            self._pending_submit_time = None
            self._submit_speech()

        self._stop_transcription_worker()
        logger.info("VAD worker stopped")

    def cleanup(self) -> None:
        if self._running.is_set():
            self.stop()
        self._pending_submit_time = None
        self._speech_buffer.clear()
        self._recent_frames.clear()
        if self._kws_detector:
            self._kws_detector.cleanup()
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
        if self._cloud_streaming:
            self._listen_loop_streaming()
        else:
            self._listen_loop_vad()

    def _listen_loop_streaming(self) -> None:
        """云端流式模式：直接将音频帧送入 DashScope，跳过 VAD 分段。"""
        queue_obj = self.audio.queue
        # KWS 模式下延迟建连（idle 不送帧会触发 23s 超时断线）
        streaming_active = not self._kws_enabled

        while self._running.is_set():
            try:
                frame = queue_obj.get(timeout=0.2)
            except Exception:
                if not self._running.is_set():
                    break
                continue

            if not isinstance(frame, np.ndarray):
                frame = np.frombuffer(frame, dtype=np.int16)

            # KWS 模式下仍需状态机控制
            if self._kws_enabled:
                if self._kws_state == "idle":
                    self._recent_frames.append(frame)
                    # idle → active 切换时建连
                    if streaming_active:
                        try:
                            self.cloud_asr.stop_streaming()
                        except Exception:
                            pass
                        streaming_active = False
                    self._kws_idle_process(frame)
                    continue
                else:
                    if not self._kws_continuous and time.time() - self._active_since > self._kws_active_timeout:
                        logger.info("KWS: active timeout, returning to IDLE")
                        self._kws_to_idle()
                        continue
                    # active 态但还没建连：建连
                    if not streaming_active:
                        try:
                            # 包装 on_sentence：每次收到最终结果时刷新超时计时器
                            def _kws_on_sentence(text, _orig=self._on_sentence):
                                self._active_since = time.time()
                                if _orig:
                                    _orig(text)
                            self.cloud_asr.start_streaming(self._on_partial, _kws_on_sentence)
                            streaming_active = True
                        except Exception as e:
                            logger.error("KWS active: 流式 ASR 建连失败: %s", e)
                            continue

            # 直接送帧，DashScope 服务端处理 VAD 和断句
            if streaming_active:
                self.cloud_asr.send_frame(frame.tobytes())

    def _listen_loop_vad(self) -> None:
        """本地 VAD 分段模式（本地 FunASR 或云端批处理）。"""
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

            # KWS mode: state machine branching
            if self._kws_enabled:
                if self._kws_state == "idle":
                    self._kws_idle_process(frame)
                    continue
                else:
                    # ACTIVE: check timeout (skip if continuous transcription)
                    if not self._kws_continuous and time.time() - self._active_since > self._kws_active_timeout:
                        logger.info("KWS: active timeout, returning to IDLE")
                        self._kws_to_idle()
                        continue

            # Feed VAD (ACTIVE or non-KWS mode)
            results = self._vad.process_frame(frame)

            speech_started_this_frame = False
            for result in results:
                if result.is_speech_start and not self._in_speech:
                    self._on_speech_start()
                    speech_started_this_frame = True
                if result.is_speech_end and self._in_speech:
                    self._on_speech_end()

            # Accumulate mic frame while in speech or during merge gap
            # Skip if speech just started this frame (already in buffer via _recent_frames)
            if self._in_speech and not speech_started_this_frame:
                self._speech_buffer.append(frame)
            elif self._pending_submit_time:
                # Keep accumulating silence during merge gap to preserve natural pauses
                self._speech_buffer.append(frame)
                if time.time() >= self._pending_submit_time:
                    self._pending_submit_time = None
                    self._submit_speech()

            # Safety: force-submit if speech buffer grows too large
            if self._in_speech:
                buf_bytes = sum(f.nbytes for f in self._speech_buffer)
                if buf_bytes >= self._max_session_bytes:
                    logger.warning("Speech buffer hit size limit (%d bytes), force submitting", buf_bytes)
                    self._in_speech = False
                    self._submit_speech()
                    self._vad.reset()

    # ------------------------------------------------------------------
    # KWS state machine
    # ------------------------------------------------------------------

    def _kws_idle_process(self, frame: np.ndarray) -> None:
        """IDLE 态：帧送 KWS 检测，命中则声纹验证。"""
        result = self._kws_detector.feed(frame)
        if result is None:
            return

        # 唤醒词命中 -> 声纹验证
        if self._speaker_processor:
            recent_audio = np.concatenate(list(self._recent_frames))
            speaker_result = self._speaker_processor.identify(recent_audio)
            if not speaker_result.is_known:
                logger.info(
                    "KWS: keyword detected but speaker verification failed (score=%.2f)",
                    speaker_result.confidence,
                )
                return
            logger.info(
                "KWS: speaker verified: %s (score=%.2f)",
                speaker_result.speaker_id,
                speaker_result.confidence,
            )

        # 验证通过 -> 进入 ACTIVE
        self._kws_to_active()

    def _kws_to_active(self) -> None:
        """切换到 ACTIVE 态。"""
        self._kws_state = "active"
        self._active_since = time.time()
        self._vad.reset()
        self._in_speech = False
        self._speech_buffer.clear()
        logger.info("KWS: entering ACTIVE mode")
        try:
            import winsound
            threading.Thread(target=winsound.Beep, args=(1200, 200), daemon=True).start()
        except Exception:
            pass

    def _kws_to_idle(self) -> None:
        """切换回 IDLE 态。"""
        self._kws_state = "idle"
        self._kws_continuous = False
        self._in_speech = False
        self._pending_submit_time = None
        self._speech_buffer.clear()
        self._kws_detector.reset()
        self._vad.reset()
        logger.info("KWS: returning to IDLE mode")
        try:
            import winsound
            threading.Thread(target=winsound.Beep, args=(500, 150), daemon=True).start()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Speech events
    # ------------------------------------------------------------------

    def _on_speech_start(self) -> None:
        self._in_speech = True
        if self._pending_submit_time:
            # Speech resumed before merge timer expired — keep accumulating
            self._pending_submit_time = None
            logger.info("VAD: speech resumed, merging with previous segment")
        else:
            # Fresh speech start
            self._speech_buffer = list(self._recent_frames)
            logger.info("VAD: speech start detected")

    def _on_speech_end(self) -> None:
        self._in_speech = False
        # Don't submit immediately; start merge timer
        self._pending_submit_time = time.time() + self._merge_gap_s
        self._vad.reset()
        logger.debug("VAD: speech end, waiting %.1fs for continuation", self._merge_gap_s)

    def _submit_speech(self) -> None:
        if not self._speech_buffer:
            return
        combined = np.concatenate(self._speech_buffer)
        self._speech_buffer.clear()

        duration_s = len(combined) / self._audio_cfg["sample_rate"]
        logger.info("VAD: submitting %.2fs of speech for transcription", duration_s)

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
                if result.is_known:
                    speaker_id = result.speaker_id
                    speaker_confidence = result.confidence
                elif self._speaker_cluster:
                    # 未注册声纹 → 聚类分离，自动标注说话人N
                    try:
                        embedding = self._speaker_processor.extract_embedding(combined)
                        speaker_id = self._speaker_cluster.assign(embedding)
                    except Exception as exc:
                        logger.warning("Speaker clustering failed: %s", exc)
                        speaker_id = result.speaker_id
                        speaker_confidence = result.confidence
                else:
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
            if self._asr_backend == "cloud":
                asr_result = self.cloud_asr.transcribe_file(tmp_path)
            else:
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

        # KWS command matching in ACTIVE mode
        if (
            self._kws_enabled
            and self._kws_state == "active"
            and self._command_dispatcher
            and result.text
        ):
            cmd = self._command_dispatcher.match(result.text)
            if cmd:
                logger.info("KWS: matched command '%s' from text: %s", cmd.name, result.text)
                if cmd.name == "exit_active":
                    self._kws_to_idle()
                    return
                elif cmd.name == "start_transcribe":
                    self._kws_continuous = True
                    logger.info("KWS: switching to continuous transcription (say '停止录音' or '退出' to return)")
                elif cmd.name == "stop_transcribe":
                    if self._kws_continuous:
                        self._kws_continuous = False
                        logger.info("KWS: continuous transcription stopped, back to ACTIVE with timeout")
                    else:
                        self._kws_to_idle()
                    return
                # Command beep
                try:
                    import winsound
                    threading.Thread(target=winsound.Beep, args=(800, 100), daemon=True).start()
                except Exception:
                    pass
                self._active_since = time.time()
                return
            else:
                # Unmatched
                if self._kws_unmatched == "ignore":
                    self._active_since = time.time()
                    return
                elif self._kws_unmatched == "hint":
                    logger.info("KWS: unrecognized command: %s", result.text)
                    self._active_since = time.time()
                    return
                # "type" mode: fall through to on_result
            self._active_since = time.time()

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
