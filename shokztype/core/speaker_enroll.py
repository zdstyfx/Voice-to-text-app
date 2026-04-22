"""CLI tool for speaker enrollment — register, list, and remove speakers."""

from __future__ import annotations

import argparse
import logging
import os
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


def _record_vad_samples(
    num_samples: int,
    sample_rate: int = 16000,
    device=None,
    min_duration: float = 1.0,
    max_duration: float = 10.0,
) -> list[np.ndarray]:
    """Record multiple speech samples using VAD auto-detection.

    Listens to microphone, uses FireRedVAD to detect speech start/end,
    and collects num_samples speech segments.
    """
    import collections
    import queue

    import sounddevice as sd

    from .config import load_config
    from .vad import VadProcessor

    config = load_config()
    vad = VadProcessor(config)
    block_ms = config["audio"].get("block_ms", 20)
    block_samples = sample_rate * block_ms // 1000
    min_samples_len = int(min_duration * sample_rate)
    max_samples_len = int(max_duration * sample_rate)

    samples_collected: list[np.ndarray] = []
    speech_buffer: list[np.ndarray] = []
    in_speech = False
    pre_speech_frames: collections.deque = collections.deque(maxlen=15)

    print(f"\n声纹注册")
    print("=" * 40)
    print(f"请说 {num_samples} 段不同的话（每段 {min_duration:.0f}-{max_duration:.0f} 秒）\n")

    audio_queue: queue.Queue = queue.Queue()

    def audio_callback(indata, frames, time_info, status):
        nonlocal in_speech, speech_buffer
        if status:
            logger.debug("Audio callback status: %s", status)
        frame = indata[:, 0].copy()
        frame_int16 = (frame * 32768).astype(np.int16)
        audio_queue.put(frame_int16)

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        blocksize=block_samples,
        dtype="float32",
        device=device,
        callback=audio_callback,
    ):
        while len(samples_collected) < num_samples:
            idx = len(samples_collected) + 1
            print(f"[{idx}/{num_samples}] 请说话...", end=" ", flush=True)

            in_speech = False
            speech_buffer = []
            pre_speech_frames.clear()
            vad.reset()

            while True:
                try:
                    frame = audio_queue.get(timeout=0.5)
                except Exception:
                    continue

                pre_speech_frames.append(frame)
                results = vad.process_frame(frame)

                for result in results:
                    if result.is_speech_start and not in_speech:
                        in_speech = True
                        speech_buffer = list(pre_speech_frames)
                    if result.is_speech_end and in_speech:
                        in_speech = False
                        combined = np.concatenate(speech_buffer)
                        duration_s = len(combined) / sample_rate

                        if len(combined) < min_samples_len:
                            print(f"太短 ({duration_s:.1f}s)，请重新说话...", end=" ", flush=True)
                            speech_buffer = []
                            continue

                        if len(combined) > max_samples_len:
                            combined = combined[:max_samples_len]
                            duration_s = len(combined) / sample_rate

                        samples_collected.append(combined)
                        print(f"完成 ({duration_s:.1f}s)")
                        break

                if in_speech:
                    speech_buffer.append(frame)
                    # Force-end if too long
                    total_len = sum(len(f) for f in speech_buffer)
                    if total_len > max_samples_len:
                        combined = np.concatenate(speech_buffer)[:max_samples_len]
                        samples_collected.append(combined)
                        duration_s = len(combined) / sample_rate
                        print(f"完成 ({duration_s:.1f}s)")
                        in_speech = False
                        break

    return samples_collected


def cmd_enroll(args: argparse.Namespace) -> None:
    config = load_config()
    config["speaker"]["enabled"] = True
    proc = SpeakerProcessor(config)

    num_samples = getattr(args, "samples", 3)
    min_samples = config["speaker"].get("min_enroll_samples", 3)
    if num_samples < min_samples:
        logger.error("Need at least %d samples, got --samples %d", min_samples, num_samples)
        sys.exit(1)

    if args.audio:
        # Single WAV file mode (backward compatible)
        audio = _read_wav(args.audio)
        embedding = proc.extract_embedding(audio)
        proc.db.enroll(args.name, embedding)
        logger.info("Enrolled: %s (1 sample from file)", args.name)
    else:
        source = getattr(args, "source", None)
        if not source:
            print("\n  录制声纹样本:")
            print("  [1] 电脑麦克风 (VAD自动检测)")
            print("  [2] ESP32 UDP 麦克风")
            choice = input("  选择 1 或 2: ").strip()
            source = "udp" if choice == "2" else "mic"

        if source == "udp":
            audio = _record_from_udp(args.duration, config)
            embedding = proc.extract_embedding(audio)
            proc.db.enroll(args.name, embedding)
            logger.info("Enrolled: %s (1 sample from UDP)", args.name)
        else:
            # VAD-guided multi-sample enrollment
            audio_samples = _record_vad_samples(
                num_samples=num_samples,
                sample_rate=config["audio"]["sample_rate"],
                device=config["audio"].get("device"),
            )
            embeddings = []
            for i, audio in enumerate(audio_samples):
                emb = proc.extract_embedding(audio)
                embeddings.append(emb)
                proc.db.enroll(args.name, emb)

            # Show inter-sample similarity
            if len(embeddings) >= 2:
                print("\n样本间相似度:")
                centroid = np.mean(embeddings, axis=0)
                centroid = centroid / (np.linalg.norm(centroid) + 1e-8)
                for i, emb in enumerate(embeddings):
                    emb_norm = emb / (np.linalg.norm(emb) + 1e-8)
                    sim = float(np.dot(emb_norm, centroid))
                    print(f"  样本 {i+1}: {sim:.4f}")

            count = proc.db._speakers.get(args.name, {}).get("sample_count", 0)
            logger.info("Enrolled: %s (%d samples)", args.name, count)

    # --add-whitelist
    if getattr(args, "add_whitelist", False):
        import json as _json

        config_path = "config.json"
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                file_cfg = _json.load(f)
        else:
            file_cfg = {}

        spk_cfg = file_cfg.setdefault("speaker", {})
        whitelist = spk_cfg.setdefault("whitelist", [])
        if args.name not in whitelist:
            whitelist.append(args.name)
            with open(config_path, "w", encoding="utf-8") as f:
                _json.dump(file_cfg, f, ensure_ascii=False, indent=2)
            logger.info("Added '%s' to whitelist in %s", args.name, config_path)
        else:
            logger.info("'%s' already in whitelist", args.name)


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
    p_enroll.add_argument(
        "--samples", type=int, default=3, help="Number of speech samples to collect (default: 3, min: 3)"
    )
    p_enroll.add_argument(
        "--add-whitelist", action="store_true", help="Add speaker to whitelist in config.json"
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
