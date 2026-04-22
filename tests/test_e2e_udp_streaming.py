"""End-to-end test: simulated ESP32 -> UDPAudioSource -> TranscriptionWorker queue."""

import socket
import struct
import time

import numpy as np
import pytest

from shokztype.core.udp_audio_source import UDPAudioSource


def _make_packet(seq: int, num_samples: int = 320) -> bytes:
    pcm = np.zeros(num_samples, dtype=np.int16).tobytes()
    return struct.pack("<I", seq) + pcm


def test_udp_source_receives_continuous_stream():
    """Simulate ESP32 sending 1 second of audio (50 packets), verify all received."""
    source = UDPAudioSource(
        esp32_host="127.0.0.1",
        esp32_port=0,
        listen_port=0,
    )
    source.start()
    port = source.local_port

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for seq in range(50):
        sock.sendto(_make_packet(seq), ("127.0.0.1", port))
        time.sleep(0.001)  # ~1ms between packets
    sock.close()

    time.sleep(0.5)

    received = 0
    while not source.queue.empty():
        frame = source.queue.get_nowait()
        assert isinstance(frame, np.ndarray)
        assert frame.dtype == np.int16
        received += 1

    source.stop()
    assert received == 50


def test_udp_source_keepalive_sends_helo():
    """Verify that UDPAudioSource sends HELO to the ESP32 address."""
    # Set up a mock "ESP32" UDP listener
    mock_esp32 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    mock_esp32.bind(("127.0.0.1", 0))
    mock_esp32.settimeout(5.0)
    esp32_port = mock_esp32.getsockname()[1]

    source = UDPAudioSource(
        esp32_host="127.0.0.1",
        esp32_port=esp32_port,
        listen_port=0,
    )
    source.start()

    # Wait for at least one HELO
    data, addr = mock_esp32.recvfrom(64)
    assert data == b"HELO"

    source.stop()
    mock_esp32.close()
