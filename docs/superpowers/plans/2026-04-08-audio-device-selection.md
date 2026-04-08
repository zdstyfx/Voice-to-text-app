# Audio Device Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "[3] 选择其他音频设备" option to the audio source menu, listing all system input devices (Bluetooth, USB, etc.) for user selection.

**Architecture:** Add a `_select_audio_device()` helper in `main.py` that calls `sounddevice.query_devices()` to enumerate input devices, displays them, and returns the selected device index. The same helper is reused in `enrollment_ui.py` for speaker registration. No new files needed — `AudioCapture` already accepts a `device` parameter.

**Tech Stack:** Python, sounddevice (already a dependency)

---

### Task 1: Add `_select_audio_device()` to `main.py`

**Files:**
- Modify: `main.py:186-196` (audio source selection menu in `_run_transcription_flow`)

- [ ] **Step 1: Add the `_select_audio_device()` function**

Add this function after the `_create_udp_source()` function (after line 289):

```python
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
        # Mark default device
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
```

- [ ] **Step 2: Update audio source menu from 2 options to 3**

Replace lines 187-196 in `_run_transcription_flow()`:

Old code:
```python
        print("\n  选择音频源:")
        print("  [1] 电脑麦克风")
        print("  [2] ESP32 UDP")
        src_choice = input("  输入 1 或 2: ").strip()
        if src_choice == "2":
            audio_cfg = config["audio"]
            esp32_host = audio_cfg.get("esp32_host", "192.168.4.1")
            esp32_port = audio_cfg.get("esp32_port", 6000)
            udp_addr = f"{esp32_host}:{esp32_port}"
            audio_source = _create_udp_source(udp_addr, config)
```

New code:
```python
        print("\n  选择音频源:")
        print("  [1] 电脑麦克风（默认设备）")
        print("  [2] ESP32 UDP")
        print("  [3] 选择其他音频设备")
        src_choice = input("  输入 1/2/3: ").strip()
        if src_choice == "2":
            audio_cfg = config["audio"]
            esp32_host = audio_cfg.get("esp32_host", "192.168.4.1")
            esp32_port = audio_cfg.get("esp32_port", 6000)
            udp_addr = f"{esp32_host}:{esp32_port}"
            audio_source = _create_udp_source(udp_addr, config)
        elif src_choice == "3":
            device_index = _select_audio_device()
            if device_index is not None:
                from app.audio_capture import AudioCapture
                audio_source = AudioCapture(
                    sample_rate=config["audio"]["sample_rate"],
                    block_ms=config["audio"]["block_ms"],
                    device=device_index,
                )
```

- [ ] **Step 3: Manual test**

Run: `python main.py`
1. Select `[1] 语音转写`
2. Select `[3] 选择其他音频设备`
3. Verify device list shows all input devices (built-in mic, Bluetooth if paired, etc.)
4. Select a device by number
5. Verify it prints the selected device name

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add audio input device selection to transcription flow"
```

---

### Task 2: Add device selection to `enrollment_ui.py`

**Files:**
- Modify: `app/enrollment_ui.py:16,48-52` (add helper + update audio source selection)
- Modify: `app/speaker_enroll.py:32` (add `device` param to `_record_audio`)

- [ ] **Step 1: Add `_select_audio_device()` helper to `enrollment_ui.py`**

Add this function before `_interactive_enroll()` (after the constants at line 16):

```python
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
```

Note: This is the same function as in `main.py`. Both files define it locally to avoid circular imports (main.py imports from app package, so app modules cannot import from main).

- [ ] **Step 2: Update enrollment audio source menu**

Replace lines 48-52 in `_interactive_enroll()`:

Old code:
```python
    # Audio source selection
    print("\n  录制音频源:")
    print("  [1] 电脑麦克风")
    print("  [2] ESP32 UDP 麦克风")
    src_choice = input("  选择 1 或 2: ").strip()
    source = "udp" if src_choice == "2" else "mic"
```

New code:
```python
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
```

- [ ] **Step 3: Pass device_index to recording function**

The existing recording call at line 84 is:
```python
                audio = _record_audio(duration)
```

Replace it to pass the device:
```python
                audio = _record_audio(duration, device=device_index)
```

This requires updating the `_record_audio` function signature in `speaker_enroll.py`.

- [ ] **Step 4: Update `_record_audio` in `speaker_enroll.py` to accept device parameter**

In `app/speaker_enroll.py`, update the function signature and `sd.rec` call:

Old code (lines 32-45):
```python
def _record_audio(duration: float, sample_rate: int = 16000) -> np.ndarray:
    """Record audio from microphone for given duration."""
    import sounddevice as sd

    logger.info("Recording %g seconds... Speak now!", duration)
    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    logger.info("Recording finished.")
    return audio.flatten()
```

New code:
```python
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
```

- [ ] **Step 5: Manual test**

Run: `python main.py`
1. Select `[3] 声纹注册/管理`
2. Select `[1] 注册说话人`
3. Enter a name
4. Select `[3] 选择其他音频设备`
5. Verify device list appears and selection works
6. Verify recording uses the selected device

- [ ] **Step 6: Commit**

```bash
git add app/enrollment_ui.py app/speaker_enroll.py
git commit -m "feat: add audio device selection to speaker enrollment"
```

---

### Task 3: Update documentation

**Files:**
- Modify: `docs/计划-声纹识别.md`

- [ ] **Step 1: Update the usage docs**

In `docs/计划-声纹识别.md`, update the "功能 [1] 语音转写" section's audio source menu (around line 44):

Old:
```
选择音频源:
[1] 电脑麦克风
[2] ESP32 UDP
```

New:
```
选择音频源:
[1] 电脑麦克风（默认设备）
[2] ESP32 UDP
[3] 选择其他音频设备
```

And update the "功能 [3] 声纹注册/管理" section's enrollment flow (around line 97):

Old:
```
录制音频源: [1] 电脑麦克风  [2] ESP32 UDP
```

New:
```
录制音频源: [1] 电脑麦克风（默认设备）  [2] ESP32 UDP  [3] 选择其他音频设备
```

Also add a note about Bluetooth devices in the "关键知识点" section, after item 3 (注册与使用必须同源):

```markdown
### 3.1 蓝牙/USB设备选择
选择「[3] 选择其他音频设备」会列出 Windows 已识别的所有输入设备（蓝牙麦克风、USB 麦克风、外接声卡等）。
蓝牙设备需先在 Windows 蓝牙设置中配对连接，vocotype 才能看到。
注意：注册声纹和运行转写时应选择同一个设备（参见第 3 点）。
```

- [ ] **Step 2: Commit**

```bash
git add "docs/计划-声纹识别.md"
git commit -m "docs: update usage docs with audio device selection option"
```
