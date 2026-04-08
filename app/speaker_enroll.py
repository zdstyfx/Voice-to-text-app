"""CLI tool for speaker enrollment — register, list, and remove speakers."""

from __future__ import annotations

import argparse
import logging
import sys
import wave

import numpy as np

from .config import load_config
from .speaker import SpeakerProcessor
from .speaker_db import SpeakerDB

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _read_wav(path: str) -> np.ndarray:
    """Read a WAV file and return int16 samples."""
    with wave.open(path, "rb") as wf:
        assert wf.getnchannels() == 1, "Only mono audio is supported"
        assert wf.getsampwidth() == 2, "Only 16-bit audio is supported"
        sr = wf.getframerate()
        if sr != 16000:
            logger.warning("Sample rate is %d, expected 16000", sr)
        frames = wf.readframes(wf.getnframes())
    return np.frombuffer(frames, dtype=np.int16)


def _record_audio(duration: float, sample_rate: int = 16000, device=None) -> np.ndarray:
    """Record audio from microphone for given duration."""
    import sounddevice as sd

    logger.info("Recording %g seconds... Speak now!", duration)
    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
        device=device,
    )
    sd.wait()
    logger.info("Recording finished.")
    return audio.flatten()


def _record_from_udp(duration: float, config: dict) -> np.ndarray:
    """Record audio from ESP32 UDP source for given duration."""
    import time
    from .udp_audio_source import UDPAudioSource

    audio_cfg = config["audio"]
    source = UDPAudioSource(
        esp32_host=audio_cfg.get("esp32_host", "192.168.4.1"),
        esp32_port=audio_cfg.get("esp32_port", 6000),
        listen_port=audio_cfg.get("listen_port", 6000),
        sample_rate=audio_cfg.get("sample_rate", 16000),
        block_ms=audio_cfg.get("block_ms", 20),
    )

    logger.info("Connecting to ESP32 UDP... Speak now! (%g seconds)", duration)
    source.start()
    frames = []
    deadline = time.time() + duration
    try:
        while time.time() < deadline:
            try:
                frame = source.queue.get(timeout=0.5)
                if not isinstance(frame, np.ndarray):
                    frame = np.frombuffer(frame, dtype=np.int16)
                frames.append(frame)
            except Exception:
                continue
    finally:
        source.stop()

    if not frames:
        logger.error("No audio received from ESP32!")
        sys.exit(1)

    logger.info("Recording finished. (%d frames)", len(frames))
    return np.concatenate(frames)


def cmd_enroll(args: argparse.Namespace) -> None:
    config = load_config()
    config["speaker"]["enabled"] = True
    proc = SpeakerProcessor(config)

    if args.audio:
        audio = _read_wav(args.audio)
    else:
        source = getattr(args, "source", None)
        if not source:
            print("\n  录制声纹样本:")
            print("  [1] 电脑麦克风")
            print("  [2] ESP32 UDP 麦克风")
            choice = input("  选择 1 或 2: ").strip()
            source = "udp" if choice == "2" else "mic"

        if source == "udp":
            audio = _record_from_udp(args.duration, config)
        else:
            audio = _record_audio(args.duration)

    min_samples = 16000  # at least 1 second
    if len(audio) < min_samples:
        logger.error("Audio too short (%.1fs), need at least 1 second", len(audio) / 16000)
        sys.exit(1)

    embedding = proc.extract_embedding(audio)
    proc.db.enroll(args.name, embedding)
    count = 0
    for s in proc.db.list_speakers():
        if s == args.name:
            count = proc.db._speakers.get(s, proc.db._auto_speakers.get(s, {})).get(
                "sample_count", 0
            )
    logger.info("Enrolled: %s (%d samples)", args.name, count)


def cmd_list(args: argparse.Namespace) -> None:
    config = load_config()
    db = SpeakerDB(config["speaker"]["db_path"])
    speakers = db.list_speakers()
    if not speakers:
        logger.info("No registered speakers.")
        return
    logger.info("Registered speakers:")
    for name in speakers:
        entry = db._speakers.get(name) or db._auto_speakers.get(name, {})
        count = entry.get("sample_count", 0)
        reg_at = entry.get("registered_at", "?")
        logger.info("  - %s (%d samples, registered %s)", name, count, reg_at)


def cmd_remove(args: argparse.Namespace) -> None:
    config = load_config()
    db = SpeakerDB(config["speaker"]["db_path"])
    if db.remove(args.name):
        logger.info("Removed: %s", args.name)
    else:
        logger.error("Speaker '%s' not found", args.name)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Speaker enrollment tool")
    sub = parser.add_subparsers(dest="command")

    # enroll
    p_enroll = sub.add_parser("enroll", help="Register a new speaker")
    p_enroll.add_argument("--name", required=True, help="Speaker name")
    p_enroll.add_argument("--audio", help="Path to WAV file (16kHz/16bit/mono)")
    p_enroll.add_argument(
        "--duration", type=float, default=10.0, help="Recording duration in seconds (default: 10)"
    )
    p_enroll.add_argument(
        "--source", choices=["mic", "udp"], help="Audio source: mic (computer) or udp (ESP32)"
    )
    p_enroll.set_defaults(func=cmd_enroll)

    # list
    p_list = sub.add_parser("list", help="List registered speakers")
    p_list.set_defaults(func=cmd_list)

    # remove
    p_remove = sub.add_parser("remove", help="Remove a speaker")
    p_remove.add_argument("--name", required=True, help="Speaker name to remove")
    p_remove.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
