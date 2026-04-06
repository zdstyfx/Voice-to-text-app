"""UDP audio source — receives ESP32 audio stream via UDP."""

from __future__ import annotations

import logging
import queue
import socket
import struct
import threading

import numpy as np

from .audio_source import AudioSource

logger = logging.getLogger(__name__)

# ESP32 packet: [seq:4B LE uint32][PCM:640B] = 644 bytes
_SEQ_BYTES = 4
_PCM_BYTES = 640
_EXPECTED_PKT = _SEQ_BYTES + _PCM_BYTES  # 644
_HELO = b"HELO"
_KEEPALIVE_INTERVAL = 2.0  # seconds


class UDPAudioSource(AudioSource):
    """Receive 16kHz/16bit/mono PCM audio from an ESP32 over UDP."""

    def __init__(
        self,
        esp32_host: str = "192.168.4.1",
        esp32_port: int = 6000,
        listen_port: int = 6000,
        sample_rate: int = 16000,
        block_ms: int = 20,
        queue_size: int = 200,
    ) -> None:
        self.esp32_host = esp32_host
        self.esp32_port = esp32_port
        self._listen_port = listen_port
        self.sample_rate = sample_rate
        self.block_ms = block_ms
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=queue_size)
        self._socket: socket.socket | None = None
        self._running = False
        self._lock = threading.Lock()
        self._receiver_thread: threading.Thread | None = None
        self._keepalive_thread: threading.Thread | None = None
        self._last_seq: int | None = None
        self._packets_received = 0
        self._packets_lost = 0

    @property
    def queue(self) -> queue.Queue[np.ndarray]:
        return self._queue

    @property
    def local_port(self) -> int:
        """Return the actual bound port (useful when listen_port=0)."""
        if self._socket is None:
            return 0
        return self._socket.getsockname()[1]

    def start(self) -> None:
        with self._lock:
            if self._running:
                return

            self.flush()
            self._last_seq = None
            self._packets_received = 0
            self._packets_lost = 0

            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.bind(("0.0.0.0", self._listen_port))
            self._socket.settimeout(1.0)

            self._running = True

            self._receiver_thread = threading.Thread(
                target=self._receiver_loop, daemon=True, name="UDPAudioReceiver"
            )
            self._receiver_thread.start()

            self._keepalive_thread = threading.Thread(
                target=self._keepalive_loop, daemon=True, name="UDPKeepalive"
            )
            self._keepalive_thread.start()

            port = self._socket.getsockname()[1]
            logger.info(
                "UDP 音频源已启动: 监听 0.0.0.0:%d, ESP32 %s:%d",
                port,
                self.esp32_host,
                self.esp32_port,
            )

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False

        # Close socket to unblock recvfrom
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

        if self._receiver_thread and self._receiver_thread.is_alive():
            self._receiver_thread.join(timeout=2)
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            self._keepalive_thread.join(timeout=3)

        self._receiver_thread = None
        self._keepalive_thread = None

        logger.info(
            "UDP 音频源已停止 (收到 %d 包, 丢失 %d 包)",
            self._packets_received,
            self._packets_lost,
        )

    def flush(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _receiver_loop(self) -> None:
        while self._running:
            try:
                data, _addr = self._socket.recvfrom(2048)
            except socket.timeout:
                continue
            except ConnectionResetError:
                # Windows: UDP ICMP port-unreachable triggers this on next recvfrom
                continue
            except OSError:
                if self._running:
                    logger.warning("UDP socket 读取错误")
                break

            if len(data) < _EXPECTED_PKT:
                logger.debug("丢弃畸形数据包 (%d 字节)", len(data))
                continue

            seq = struct.unpack_from("<I", data, 0)[0]
            pcm = np.frombuffer(data[_SEQ_BYTES:_SEQ_BYTES + _PCM_BYTES], dtype=np.int16).copy()

            # Packet loss detection
            if self._last_seq is not None:
                expected = (self._last_seq + 1) & 0xFFFFFFFF
                if seq != expected:
                    gap = (seq - expected) & 0xFFFFFFFF
                    if gap < 1000:  # reasonable gap
                        self._packets_lost += gap
                        logger.warning("UDP 丢包: 期望 seq=%d 收到 seq=%d (丢失 %d 包)", expected, seq, gap)
            self._last_seq = seq
            self._packets_received += 1

            try:
                self._queue.put_nowait(pcm)
            except queue.Full:
                logger.warning("音频队列已满，丢弃帧 seq=%d", seq)

    def _keepalive_loop(self) -> None:
        """Periodically send HELO to ESP32 to maintain the UDP path."""
        while self._running:
            try:
                if self._socket:
                    self._socket.sendto(_HELO, (self.esp32_host, self.esp32_port))
                    logger.debug("已发送 HELO 到 %s:%d", self.esp32_host, self.esp32_port)
            except OSError as exc:
                if self._running:
                    logger.debug("发送 HELO 失败: %s", exc)

            # Sleep in small increments so we can exit quickly
            for _ in range(int(_KEEPALIVE_INTERVAL * 10)):
                if not self._running:
                    return
                threading.Event().wait(0.1)
