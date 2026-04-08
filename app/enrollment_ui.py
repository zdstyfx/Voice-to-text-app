"""Interactive speaker enrollment UI — sub-menu for register/list/remove with multi-sample support."""

from __future__ import annotations

import logging
import sys
from typing import Dict, Any

from .config import load_config
from .speaker_db import SpeakerDB

logger = logging.getLogger(__name__)

MAX_SAMPLES = 5
DEFAULT_DURATION = 5.0


def _select_audio_device() -> int | None:
    """List all system input devices and let user pick one. Returns device index or None."""
    import sounddevice as sd

    devices = sd.query_devices()
    input_devices = []
    for idx, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            input_devices.append((idx, dev["name"]))

    if not input_devices:
        print("  未找到可用的输入设备")
        return None

    print("\n  可用输入设备:")
    for i, (idx, name) in enumerate(input_devices, 1):
        default_in = sd.default.device[0]
        marker = " (默认)" if idx == default_in else ""
        print(f"  [{i}] {name}{marker}")

    sel = input("\n  输入序号: ").strip()
    if not sel.isdigit() or not (1 <= int(sel) <= len(input_devices)):
        print("  无效选择，使用默认设备")
        return None

    chosen_idx, chosen_name = input_devices[int(sel) - 1]
    print(f"  已选择: {chosen_name}")
    return chosen_idx


def run_enrollment_menu(config: Dict[str, Any]) -> None:
    """Interactive enrollment sub-menu. Returns when user selects 'back'."""
    while True:
        print("\n  === 声纹注册/管理 ===\n")
        print("  [1] 注册说话人")
        print("  [2] 查看已注册")
        print("  [3] 删除说话人")
        print("  [4] 返回主菜单")
        choice = input("\n  输入 1/2/3/4: ").strip()

        if choice == "1":
            _interactive_enroll(config)
        elif choice == "2":
            _interactive_list(config)
        elif choice == "3":
            _interactive_remove(config)
        elif choice == "4" or choice == "":
            return
        else:
            print("  无效选择")


def _interactive_enroll(config: Dict[str, Any]) -> None:
    """Register a speaker with multi-sample recording loop."""
    name = input("\n  输入说话人姓名: ").strip()
    if not name:
        print("  姓名不能为空")
        return

    # Audio source selection
    print("\n  录制音频源:")
    print("  [1] 电脑麦克风（默认设备）")
    print("  [2] ESP32 UDP 麦克风")
    print("  [3] 选择其他音频设备")
    src_choice = input("  选择 1/2/3: ").strip()
    source = "mic"
    device_index = None
    if src_choice == "2":
        source = "udp"
    elif src_choice == "3":
        device_index = _select_audio_device()

    # Duration
    dur_input = input(f"  录制时长 (秒, 默认{DEFAULT_DURATION:.0f}): ").strip()
    try:
        duration = float(dur_input) if dur_input else DEFAULT_DURATION
    except ValueError:
        duration = DEFAULT_DURATION

    # Load speaker processor (loads CAM++ model)
    print("\n  加载声纹模型...")
    try:
        from .speaker import SpeakerProcessor
        config["speaker"]["enabled"] = True
        proc = SpeakerProcessor(config)
    except Exception as exc:
        logger.error("声纹模型加载失败: %s", exc)
        return

    # Import recording functions from speaker_enroll
    from .speaker_enroll import _record_audio, _record_from_udp

    # Multi-sample recording loop
    sample_num = 0
    for i in range(MAX_SAMPLES):
        sample_num = i + 1
        print(f"\n  --- 第 {sample_num} 个样本 ---")

        try:
            if source == "udp":
                audio = _record_from_udp(duration, config)
            else:
                audio = _record_audio(duration, device=device_index)
        except KeyboardInterrupt:
            print("\n  录制中断")
            break
        except Exception as exc:
            logger.error("录制失败: %s", exc)
            break

        # Validate audio length
        min_samples = 16000  # at least 1 second
        if len(audio) < min_samples:
            print(f"  音频太短 ({len(audio) / 16000:.1f}s)，需要至少 1 秒")
            sample_num -= 1
            continue

        # Extract embedding and enroll
        try:
            embedding = proc.extract_embedding(audio)
            proc.db.enroll(name, embedding)
        except Exception as exc:
            logger.error("声纹提取失败: %s", exc)
            sample_num -= 1
            continue

        # Get current sample count from DB
        entry = proc.db._speakers.get(name, {})
        count = entry.get("sample_count", sample_num)
        print(f"  已注册: {name} ({count} 个样本)")

        # Ask for more unless at max
        if sample_num < MAX_SAMPLES:
            more = input("\n  录制更多样本? (y/n, 默认n): ").strip().lower()
            if more != "y":
                break

    if sample_num > 0:
        entry = proc.db._speakers.get(name, {})
        total = entry.get("sample_count", 0)
        print(f"\n  注册完成: {name} (共 {total} 个样本)")
    else:
        print("\n  未注册任何样本")


def _interactive_list(config: Dict[str, Any]) -> None:
    """List all registered speakers with details."""
    db = SpeakerDB(config["speaker"]["db_path"])
    speakers = db.list_speakers()
    if not speakers:
        print("\n  无已注册说话人")
        return

    print(f"\n  已注册说话人 ({len(speakers)} 人):")
    for i, name in enumerate(speakers, 1):
        entry = db._speakers.get(name) or db._auto_speakers.get(name, {})
        count = entry.get("sample_count", 0)
        reg_at = entry.get("registered_at", "?")
        print(f"  [{i}] {name} — {count} 个样本, 注册于 {reg_at}")


def _interactive_remove(config: Dict[str, Any]) -> None:
    """Remove a speaker interactively."""
    db = SpeakerDB(config["speaker"]["db_path"])
    speakers = db.list_speakers()
    if not speakers:
        print("\n  无已注册说话人")
        return

    print(f"\n  已注册说话人:")
    for i, name in enumerate(speakers, 1):
        print(f"  [{i}] {name}")

    sel = input("\n  输入要删除的编号 (或直接输入姓名): ").strip()
    if not sel:
        return

    # Resolve by number or name
    if sel.isdigit() and 1 <= int(sel) <= len(speakers):
        target = speakers[int(sel) - 1]
    elif sel in speakers:
        target = sel
    else:
        print(f"  未找到: {sel}")
        return

    confirm = input(f"  确认删除 '{target}'? (y/n): ").strip().lower()
    if confirm != "y":
        print("  已取消")
        return

    if db.remove(target):
        print(f"  已删除: {target}")
    else:
        print(f"  删除失败: {target}")
