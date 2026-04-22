"""Tests for UDPAudioSource."""

import socket
import struct
import time

import numpy as np
import pytest

from shokztype.core.udp_audio_source import UDPAudioSource


@pytest.fixture
def source():
    """Create a UDPAudioSource on a random port, no real ESP32 needed."""
    src = UDPAudioSource(
        esp32_host="127.0.0.1",
        esp32_port=0,  # will be overridden
        listen_port=0,  # OS picks a free port
    )
    yield src
    src.stop()


def _make_packet(seq: int, num_samples: int = 320) -> bytes:
    """Build a fake ESP32 audio packet: [seq:4B LE][PCM:640B]."""
    pcm = np.arange(num_samples, dtype=np.int16).tobytes()
    return struct.pack("<I", seq) + pcm


def test_receives_packet_into_queue(source: UDPAudioSource):
    source.start()
    port = source.local_port

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(_make_packet(0), ("127.0.0.1", port))
    sock.close()

    time.sleep(0.1)
    assert not source.queue.empty()
    frame = source.queue.get_nowait()
    assert isinstance(frame, np.ndarray)
    assert frame.dtype == np.int16
    assert len(frame) == 320


def test_strips_sequence_header(source: UDPAudioSource):
    source.start()
    port = source.local_port

    pcm_data = np.full(320, 42, dtype=np.int16)
    pkt = struct.pack("<I", 99) + pcm_data.tobytes()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(pkt, ("127.0.0.1", port))
    sock.close()

    time.sleep(0.1)
    frame = source.queue.get_nowait()
    np.testing.assert_array_equal(frame, pcm_data)


def test_drops_malformed_packet(source: UDPAudioSource):
    source.start()
    port = source.local_port

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(b"short", ("127.0.0.1", port))
    sock.close()

    time.sleep(0.1)
    assert source.queue.empty()


def test_start_stop_lifecycle(source: UDPAudioSource):
    source.start()
    assert source.local_port > 0
    source.stop()
    # Double stop should not raise
    source.stop()


def test_flush_clears_queue(source: UDPAudioSource):
    source.start()
    port = source.local_port

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for i in range(5):
        sock.sendto(_make_packet(i), ("127.0.0.1", port))
    sock.close()

    time.sleep(0.1)
    assert not source.queue.empty()
    source.flush()
    assert source.queue.empty()
