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


class AudioCaptureError(Exception):
    pass


class AudioCapture(AudioSource):
    """sounddevice 麦克风采集。

    音频流在构造时即打开（常开），start()/stop() 仅控制是否将帧入队，
    避免热键模式下反复开关硬件流导致的启动延迟。
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
        self._capturing = False  # 是否正在采集（帧入队列）

        self._block_size = int(self.sample_rate * self.block_ms / 1000)
        # 预缓冲：始终保留最近帧，start() 时补入队列避免开头丢字
        # 20 帧 × 20ms = 400ms，覆盖 ASR WebSocket 连接建立时间
        self._pre_buffer: collections.deque = collections.deque(maxlen=20)
        if self._block_size <= 0:
            raise ValueError("block_ms too small for selected sample rate")

        # 流在构造时即打开，常驻运行
        self._stream = self._open_stream(self.device)
        self._stream.start()
        logger.info(
            "音频流已打开（常驻），采样率=%sHz，块大小=%s样本，设备=%s",
            self.sample_rate, self._block_size, self._stream.device,
        )

    @property
    def queue(self) -> "queue.Queue[np.ndarray]":
        return self._queue

    def get_pre_buffer(self) -> "np.ndarray | None":
        """返回预缓冲中的音频拼接结果（供声纹验证等用途）。"""
        frames = list(self._pre_buffer)
        if not frames:
            return None
        import numpy as np
        return np.concatenate(frames)

    def start(self) -> None:
        with self._lock:
            if self._capturing:
                return
            self.flush()
            # 将预缓冲中的帧补入队列（最近 ~100ms）
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
        """重新打开硬件流（PortAudio 重初始化后调用）。"""
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
        """关闭硬件流（仅在 worker 销毁时调用）。"""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _open_stream(self, device) -> sd.RawInputStream:
        # sounddevice 要求整数索引；字符串会被当作名称模式匹配
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
            # PortAudio 可能状态异常，先重新初始化
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
            # 未采集时仍维护预缓冲，供 start() 时补入
            self._pre_buffer.append(frame)
            return
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            pass
