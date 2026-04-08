# 系统音频设备选择 — 设计文档

## 目标

在 vocotype 的音频源选择菜单中新增「选择其他音频设备」选项，让用户可以从 Windows 已识别的所有音频输入设备中选择（蓝牙麦克风、USB 麦克风、外接声卡等）。

## 当前状态

音频源选择菜单：
```
选择音频源:
[1] 电脑麦克风
[2] ESP32 UDP
```

`AudioCapture` 构造函数已支持 `device` 参数（传给 `sounddevice.RawInputStream`），但目前 main.py 交互流程中没有暴露设备选择。

## 设计

### 菜单变更

```
选择音频源:
[1] 电脑麦克风（默认设备）
[2] ESP32 UDP
[3] 选择其他音频设备
```

### 选择 [3] 后的交互流程

1. 调用 `sounddevice.query_devices()` 获取所有设备
2. 筛选出 `max_input_channels > 0` 的输入设备
3. 列出设备名称和序号：
   ```
   可用输入设备:
   [1] Microphone (Realtek High Definition Audio)
   [2] Headset (My Bluetooth Device)
   [3] CABLE Output (VB-Audio Virtual Cable)
   → 输入序号:
   ```
4. 用户选择后，使用 sounddevice 设备 index 创建 `AudioCapture(device=index)`

### 实现细节

- 在 `main.py` 中新增 `_select_audio_device()` 函数
- 该函数返回 sounddevice 设备 index（int）
- 如果无可用输入设备，打印提示并返回 None（退化为默认设备）
- 选中设备后，后续创建 `AudioCapture` 时传入 `device=index`

### 声纹注册同步

声纹注册（`enrollment_ui.py`）中"录制音频源"选择也需要同步支持设备选择，确保注册和使用可以用同一个蓝牙设备。

## 改动文件

| 文件 | 改动 |
|------|------|
| `main.py` | 新增 `_select_audio_device()` 函数；音频源菜单加 `[3]`；声纹注册菜单同步 |
| `app/enrollment_ui.py` | 录制音频源选择加 `[3] 选择其他音频设备` |

## 不改动的文件

- `app/audio_capture.py` — 已支持 `device` 参数
- `app/audio_source.py` — 接口不变
- `app/config.py` — 无需新配置
- `app/vad_worker.py` — 不涉及

## 风险

- 蓝牙音频设备可能不支持 16kHz 采样率 → sounddevice 会自动重采样（由操作系统 WASAPI 层处理）
- 蓝牙设备断连 → AudioCapture 已有 fallback 逻辑（捕获异常、尝试默认设备）
