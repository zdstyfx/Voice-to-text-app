"""ESP32 wireless microphone receiver — beacon/HELO handshake + UDP audio + VB-Cable routing."""

from __future__ import annotations

import logging
import queue
import socket
import struct
import threading
import time
from typing import Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

# Protocol constants (must match ESP32 firmware)
ESP32_IP = "192.168.4.1"
ESP32_PORT = 6000
BEACON_PORT = 6001
AUDIO_PKT_SIZE = 644       # [seq:4B][PCM:640B]
PCM_BYTES_PER_PKT = 640    # 320 samples * 2 bytes
KEEPALIVE_INTERVAL = 2
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
JITTER_PREBUFFER_PKTS = 4   # 4 packets = 80ms pre-buffer


def find_vbcable_device() -> tuple[Optional[int], Optional[str]]:
    """Auto-detect VB-Cable Input device. Returns (device_id, name) or (None, None)."""
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        name = dev["name"].lower()
        if "cable input" in name and dev["max_output_channels"] > 0:
            return i, dev["name"]
    return None, None


def list_output_devices() -> None:
    """Print all available audio output devices."""
    devices = sd.query_devices()
    print("  可用输出设备:")
    print(f"  {'ID':>4}  {'名称':<45} {'通道':>4}  {'采样率':>8}")
    print(f"  {'-' * 68}")
    for i, dev in enumerate(devices):
        if dev["max_output_channels"] > 0:
            rate = int(dev["default_samplerate"])
            marker = " <-- VB-Cable" if "cable input" in dev["name"].lower() else ""
            print(f"  {i:>4}  {dev['name']:<45} {dev['max_output_channels']:>4}  {rate:>8}{marker}")


def run_esp32_receiver(
    device_id: Optional[int] = None,
    save_file: Optional[str] = None,
    duration: float = 0,
) -> None:
    """Run ESP32 wireless microphone receiver.

    Blocks until Ctrl+C or duration reached. Returns cleanly (no sys.exit).

    Args:
        device_id: Audio output device ID (None = auto-detect VB-Cable or default).
        save_file: Path to save raw PCM file, or None for playback only.
        duration: Max duration in seconds (0 = unlimited).
    """
    # Device selection
    if device_id is not None:
        dev_info = sd.query_devices(device_id)
        print(f"  输出设备: [{device_id}] {dev_info['name']}")
    else:
        vb_id, vb_name = find_vbcable_device()
        if vb_id is not None:
            device_id = vb_id
            print(f"  检测到 VB-Cable: [{vb_id}] {vb_name}")
        else:
            print("  未检测到 VB-Cable，使用默认输出设备")

    stop = threading.Event()

    # Jitter buffer
    audio_q: queue.Queue[bytes] = queue.Queue(maxsize=50)
    prebuf_ready = threading.Event()

    def audio_callback(outdata, frames, time_info, status):
        if not prebuf_ready.is_set():
            outdata[:] = 0
            return
        filled = 0
        while filled < frames:
            try:
                chunk = audio_q.get_nowait()
            except queue.Empty:
                outdata[filled:] = 0
                return
            samples = np.frombuffer(chunk, dtype=np.int16)
            n = min(len(samples), frames - filled)
            outdata[filled:filled + n, 0] = samples[:n]
            filled += n
            if n < len(samples):
                leftover = samples[n:].tobytes()
                try:
                    audio_q.put_nowait(leftover)
                except queue.Full:
                    pass

    # Audio output stream
    stream = sd.OutputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        blocksize=320,
        device=device_id,
        callback=audio_callback,
    )

    # UDP socket (beacon port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", BEACON_PORT))
    sock.settimeout(1.0)

    # Wait for beacon
    print(f"  等待 ESP32 beacon (port {BEACON_PORT})...")
    try:
        while not stop.is_set():
            try:
                data, addr = sock.recvfrom(64)
                if data == b"ESP32-MIC":
                    print(f"  收到 beacon from {addr[0]}")
                    break
            except socket.timeout:
                continue
    except KeyboardInterrupt:
        sock.close()
        return

    if stop.is_set():
        sock.close()
        return

    # HELO handshake
    sock.sendto(b"HELO", (ESP32_IP, ESP32_PORT))
    print(f"  已发送 HELO -> {ESP32_IP}:{ESP32_PORT}")

    # Keepalive thread
    def keepalive():
        while not stop.is_set():
            try:
                sock.sendto(b"HELO", (ESP32_IP, ESP32_PORT))
            except OSError:
                break
            stop.wait(KEEPALIVE_INTERVAL)

    threading.Thread(target=keepalive, daemon=True).start()

    # Receive + playback
    total_bytes = 0
    total_pkts = 0
    last_seq = -1
    lost_pkts = 0
    start_time = time.time()

    mode_hint = "实时播放" if save_file is None else f"实时播放 + 保存 -> {save_file}"
    print(f"  {mode_hint}  (16kHz/16bit/Mono)")
    if duration > 0:
        print(f"  时长限制: {duration}s")
    print("  Ctrl+C 停止\n")

    out_file = None if save_file is None else open(save_file, "wb")
    stream.start()

    try:
        while not stop.is_set():
            if duration > 0 and (time.time() - start_time) >= duration:
                break
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            if len(data) < AUDIO_PKT_SIZE:
                continue

            seq = struct.unpack("<I", data[:4])[0]
            pcm = data[4:AUDIO_PKT_SIZE]

            if last_seq >= 0 and seq > last_seq + 1:
                lost_pkts += seq - last_seq - 1
            last_seq = seq

            # Write to jitter buffer
            try:
                audio_q.put_nowait(pcm)
            except queue.Full:
                audio_q.get_nowait()
                audio_q.put_nowait(pcm)

            if not prebuf_ready.is_set() and audio_q.qsize() >= JITTER_PREBUFFER_PKTS:
                prebuf_ready.set()

            if out_file:
                out_file.write(pcm)

            total_bytes += len(pcm)
            total_pkts += 1

            if total_pkts % 50 == 0:
                elapsed = time.time() - start_time
                loss = lost_pkts / (total_pkts + lost_pkts) * 100 if (total_pkts + lost_pkts) else 0
                qsize = audio_q.qsize()
                print(f"\r  {elapsed:.1f}s | {total_pkts} pkts | {total_bytes // 1024} KB | "
                      f"丢包 {lost_pkts} ({loss:.1f}%) | buf {qsize}",
                      end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        stream.stop()
        stream.close()
        if out_file:
            out_file.close()
        sock.close()

    elapsed = time.time() - start_time
    expected = total_pkts + lost_pkts
    loss = lost_pkts / expected * 100 if expected else 0
    pps = total_pkts / elapsed if elapsed > 0 else 0
    print(f"\n\n  {'=' * 48}")
    print(f"  时长:     {elapsed:.1f}s")
    print(f"  收到:     {total_pkts} 包 ({total_bytes // 1024} KB)")
    print(f"  丢包:     {lost_pkts} ({loss:.1f}%)")
    print(f"  包速率:   {pps:.1f} pkt/s (期望 50)")
    dev_name = sd.query_devices(device_id)["name"] if device_id is not None else "默认"
    print(f"  输出设备: {dev_name}")
    print(f"  {'=' * 48}")
    if save_file:
        print(f"  已保存: {save_file}")
