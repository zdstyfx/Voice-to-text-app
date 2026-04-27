"""Microphone audio capture via sounddevice."""

import collections
import logging
import queue
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from .audio_source import AudioSource

logger = logging.getLogger(__name__)

_IDLE_CLOSE_DELAY = 5.0  # 停止采集后延迟多久关闭硬件流（秒）


class AudioCaptureError(Exception):
    pass


class AudioCapture(AudioSource):
    """sounddevice 麦克风采集。

    按需开流：start() 打开硬件流，stop() 后延迟关闭。
    短时间内再次 start() 则复用已有流，避免重复开关的延迟。
    """

    def __init__(
        self,
        sample_rate: int,
        block_ms: int,
        device: Optional[str] = None,
        queue_size: int = 200,
    ) -> None:
        self.sample_rate = sample_rate
        self.block_ms = block_ms
        self.device = device
        self._queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=queue_size)
        self._lock = threading.Lock()
        self._capturing = False
        self._stream: Optional[sd.RawInputStream] = None
        self._close_timer: Optional[threading.Timer] = None

        self._block_size = int(self.sample_rate * self.block_ms / 1000)
        self._pre_buffer: collections.deque = collections.deque(maxlen=20)
        if self._block_size <= 0:
            raise ValueError("block_ms too small for selected sample rate")

    @property
    def queue(self) -> "queue.Queue[np.ndarray]":
        return self._queue

    def get_pre_buffer(self) -> "np.ndarray | None":
        frames = list(self._pre_buffer)
        if not frames:
            return None
        return np.concatenate(frames)

    def start(self) -> None:
        with self._lock:
            if self._capturing:
                return
            # 取消延迟关闭
            if self._close_timer is not None:
                self._close_timer.cancel()
                self._close_timer = None
            # 流没开则打开
            if self._stream is None:
                self._stream = self._open_stream(self.device)
                self._stream.start()
                logger.info("音频流已打开，设备=%s", self._stream.device)
            self.flush()
            for frame in self._pre_buffer:
                try:
                    self._queue.put_nowait(frame)
                except queue.Full:
                    break
            self._pre_buffer.clear()
            self._capturing = True
            logger.info("音频采集已启动")

    def stop(self) -> None:
        with self._lock:
            if not self._capturing:
                return
            self._capturing = False
            logger.info("音频采集已停止")
            # 延迟关闭硬件流：短时间内再 start 可复用
            if self._close_timer is not None:
                self._close_timer.cancel()
            self._close_timer = threading.Timer(
                _IDLE_CLOSE_DELAY, self._delayed_close,
            )
            self._close_timer.daemon = True
            self._close_timer.start()

    def _delayed_close(self) -> None:
        with self._lock:
            if self._capturing:
                return  # 已经重新 start 了
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
                logger.info("音频流已关闭（空闲超时）")
            self._close_timer = None

    @property
    def is_running(self) -> bool:
        return self._capturing

    def flush(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def reopen_stream(self) -> None:
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
            self._stream = self._open_stream(self.device)
            self._stream.start()
            logger.info("音频流已重新打开，设备=%s", self._stream.device)

    def cleanup(self) -> None:
        if self._close_timer is not None:
            self._close_timer.cancel()
            self._close_timer = None
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _open_stream(self, device) -> sd.RawInputStream:
        if isinstance(device, str) and device.isdigit():
            device = int(device)
        try:
            return sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=self._block_size,
                dtype="int16",
                channels=1,
                callback=self._callback,
                device=device,
            )
        except Exception as first_err:
            logger.warning("设备 %s 打开失败: %s，尝试刷新后回退", device, first_err)
            try:
                sd._terminate()
                sd._initialize()
            except Exception:
                pass
            fb = self._fallback_device()
            logger.warning("回退至设备 #%s", fb)
            try:
                return sd.RawInputStream(
                    samplerate=self.sample_rate,
                    blocksize=self._block_size,
                    dtype="int16",
                    channels=1,
                    callback=self._callback,
                    device=fb,
                )
            except Exception as exc:
                msg = f"无法创建音频输入流: {exc}"
                logger.error(msg)
                raise AudioCaptureError(msg) from exc

    def _fallback_device(self) -> Optional[int]:
        try:
            devices = sd.query_devices()
            for idx, info in enumerate(devices):
                if info.get("max_input_channels", 0) > 0:
                    logger.warning(
                        "回退至输入设备 #%s (%s)", idx, info.get("name", "unknown")
                    )
                    return idx
        except Exception as exc:
            logger.error("查询音频设备失败: %s", exc)
        return None

    def _callback(self, in_data, frames, time, status):  # type: ignore[override]
        if status:
            logger.warning("音频流状态: %s", status)

        frame = np.frombuffer(in_data, dtype=np.int16).copy()

        if not self._capturing:
            self._pre_buffer.append(frame)
            return

        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            pass
