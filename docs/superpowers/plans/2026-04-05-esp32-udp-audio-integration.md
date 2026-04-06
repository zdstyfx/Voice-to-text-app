# ESP32 UDP 音频集成实施计划

**Goal:** 将 ESP32-S3 无线麦克风作为 UDP 音频源集成到 VocoType，实现实时语音转文字。

**Architecture:** 新增 `AudioSource` 抽象基类，让现有 `AudioCapture` 和新建 `UDPAudioSource` 都实现该接口。`TranscriptionWorker` 通过依赖注入接受任意音频源。`main.py` 新增 `--udp` 参数切换音频源。UDP 模式和麦克风模式统一使用 F2 热键控制录音开始/停止。

**Tech Stack:** Python 3.11 (venv), FunASR (ONNX), socket (UDP), numpy, threading

**设计文档:** `docs/superpowers/specs/2026-04-05-esp32-udp-audio-integration-design.md`

**环境要求:** 使用 `uv venv --python 3.11` 创建虚拟环境（Python 3.14 不兼容 funasr_onnx），需额外安装 `torch` CPU 版

---

## 一、操作流程

### 1.1 环境搭建

```powershell
# 1. 安装 uv（如果还没装）
pip install uv

# 2. 在项目目录下创建 Python 3.11 虚拟环境
cd D:\MVP\vovotyoe\vocotype
uv venv --python 3.11
# uv 会自动下载 Python 3.11（若本地没有）

# 3. 激活虚拟环境
.\.venv\Scripts\Activate.ps1
# 成功后命令行前缀出现 (vocotype)

# 4. 安装项目依赖
uv pip install -r requirements.txt

# 5. 安装 CPU 版 PyTorch（funasr_onnx 的 sensevoice_bin 无条件导入 torch）
uv pip install torch --index-url https://download.pytorch.org/whl/cpu

# 6. 安装测试工具
uv pip install pytest
```

### 1.2 ESP32 硬件准备

1. **ESP32 固件不需要改动**，它已经：
   - 以 AP 模式创建热点：SSID `ESP32-MIC`，密码 `12345678`
   - 通过 UDP 端口 6000 发送音频包：`[seq:4B 小端序][PCM:640B]` = 644 字节/包
   - 音频格式：16kHz、16bit 有符号整型、单声道、20ms/包（50 包/秒）
   - 收到客户端 `HELO` 后开始发送，5 秒未收到 `HELO` 断开
2. ESP32 固件代码位置：`D:\MVP\esp32_mic\01_audio_es8311\main\main.c`
3. ESP32 的 ES8311 codec 配置为单声道录音，麦克风增益 25.0dB，I2S 立体声模式

### 1.3 连接与运行

```powershell
# 1. 将 Windows 电脑 WiFi 连接到 ESP32 热点
#    SSID: ESP32-MIC / 密码: 12345678
#    连接后：ESP32 IP=192.168.4.1，电脑 IP=192.168.4.x

# 2. 激活虚拟环境
cd D:\MVP\vovotyoe\vocotype
.\.venv\Scripts\Activate.ps1

# 3. 启动 UDP 模式
python main.py --udp 192.168.4.1:6000

# 4. 启动麦克风模式（不加 --udp）
python main.py

# 操作方式（两种模式相同）：
#   按 F2（松开）→ 开始录音（高音提示 + 屏幕右上角红色"录音中"浮窗）
#   再按 F2（松开）→ 停止录音并转录（低音提示 + 浮窗消失）
#   转录结果自动通过 SendInput 输入到当前焦点窗口
#   终端可放在后台，通过提示音和置顶浮窗感知录音状态
#   Ctrl+C 退出
```

### 1.4 运行测试

```powershell
# 在虚拟环境中运行
python -m pytest tests/ -v
# 预期：10 tests PASS
```

### 1.5 数据流

```
ESP32-S3 (192.168.4.1:6000)                    电脑麦克风 (sounddevice)
    │ UDP 644B packets                               │ PCM frames
    ▼                                                 ▼
UDPAudioSource                               AudioCapture
    │                                                 │
    └──────────── queue.Queue[np.ndarray] ────────────┘
                           │
                           ▼
                  TranscriptionWorker
                  ├─ _capture_loop: queue.get() → buffer.append()
                  └─ stop() → _combine_buffer() → _transcription_queue
                           │
                           ▼
                  FunASR (ONNX 本地推理)
                  ├─ Paraformer ASR 模型
                  └─ CT-Transformer 标点恢复
                           │
                           ▼
                  Windows SendInput → 当前焦点应用
```

### 1.6 录音状态反馈

终端可放在后台，用户通过以下方式感知录音状态：

| 状态 | 提示音 | 浮窗（屏幕右上角） |
|------|--------|-------------------|
| 开始录音 | 高音 1000Hz × 150ms | 红色置顶浮窗 `● 录音中...` 出现 |
| 停止录音 | 低音 600Hz × 150ms | 浮窗立即消失 |

- 提示音通过 `winsound.Beep` 播放，后台线程不阻塞
- 浮窗基于 tkinter（Python 内置），无额外依赖，半透明置顶显示
- 浮窗在独立 daemon 线程运行，程序退出时自动销毁

---

## 二、任务执行记录

### Task 1: 创建 AudioSource 抽象基类 ✅

**Files:** `app/audio_source.py`, `tests/test_audio_source.py`

- [x] 创建 `AudioSource` ABC（queue/start/stop/flush 四个抽象方法）
- [x] 写测试验证 ABC 不能直接实例化 + 子类可以实例化
- [x] 运行测试：2 tests PASS
- [x] 更新 `app/__init__.py` 导出 `AudioSource`

### Task 2: AudioCapture 继承 AudioSource ✅

**Files:** `app/audio_capture.py`, `tests/test_audio_source.py`

- [x] 修改 `AudioCapture` 继承 `AudioSource`，添加 `from .audio_source import AudioSource`
- [x] 追加测试验证 `issubclass(AudioCapture, AudioSource)`
- [x] 运行测试：3 tests PASS

### Task 3: 创建 UDPAudioSource ✅

**Files:** `app/udp_audio_source.py`, `tests/test_udp_audio_source.py`

- [x] 写 5 个测试（收包、剥离序列号、丢弃畸形包、生命周期、flush）
- [x] 实现 `UDPAudioSource`：接收线程 + HELO 保活线程 + 丢包检测
- [x] **Windows 兼容修复**：`_receiver_loop` 中捕获 `ConnectionResetError`
- [x] 运行测试：5 tests PASS
- [x] 更新 `app/__init__.py` 导出 `UDPAudioSource`

### Task 4: 扩展配置支持 UDP 参数 ✅

**Files:** `app/config.py`

- [x] 在 `DEFAULT_CONFIG["audio"]` 中添加 `type`、`esp32_host`、`esp32_port`、`listen_port`
- [x] 验证配置加载：`microphone 192.168.4.1`

### Task 5: TranscriptionWorker 支持依赖注入 ✅

**Files:** `app/transcribe.py`

- [x] 添加 `from .audio_source import AudioSource` 导入
- [x] `__init__` 增加 `audio_source: Optional[AudioSource] = None` 参数
- [x] 当提供 `audio_source` 时使用它，否则创建 `AudioCapture`
- [x] ~~流式模式/VAD 已移除~~ — UDP 模式使用与麦克风相同的 `_capture_loop`
- [x] 运行测试：10 tests PASS

### Task 6: main.py 添加 --udp 参数 ✅

**Files:** `main.py`

- [x] 添加 `--udp HOST:PORT` 命令行参数
- [x] 解析 UDP 参数，创建 `UDPAudioSource` 并注入 `TranscriptionWorker`
- [x] UDP 模式和麦克风模式统一使用 F2 热键控制
- [x] **F2 热键修复**：改用 `keyboard.on_release_key` 避免按住按键时键盘重复导致多次触发
- [x] 验证 `--help` 输出正确

### Task 7: 端到端集成测试 ✅

**Files:** `tests/test_e2e_udp_streaming.py`

- [x] 模拟 ESP32 发 50 包（1 秒音频），验证全部接收
- [x] 验证 HELO 保活发送到 ESP32 地址
- [x] 运行测试：2 tests PASS

### Task 8: 全量测试并最终验证 ✅

- [x] 运行所有测试：10 tests PASS
- [x] 验证 `--udp` 模式可以启动，模型正常加载（~5.5 秒）
- [x] 真机验证：ESP32 UDP 模式 + 麦克风模式均可正常录制和转录

### Task 9: 录音状态反馈（提示音 + 置顶浮窗） ✅

**Files:** `main.py`

- [x] 添加 `RecordingOverlay` 类：基于 tkinter 的置顶半透明浮窗，显示在屏幕右上角
- [x] 按 F2 开始录音 → 高音提示（1000Hz）+ 红色浮窗 `● 录音中...` 出现
- [x] 再按 F2 停止录音 → 低音提示（600Hz）+ 浮窗立即消失
- [x] 提示音通过 `winsound.Beep` 在后台线程播放，不阻塞主线程
- [x] 浮窗运行在独立 daemon 线程，通过 `threading.Event` 跨线程控制显示/隐藏
- [x] 终端可放在后台运行，用户通过提示音和置顶浮窗感知录音状态
- [x] 程序退出时自动销毁浮窗

---

## 三、遇到的问题与解决方案

### 问题 1: Windows UDP ConnectionResetError

**现象:** UDPAudioSource 测试中，`_receiver_loop` 在 `recvfrom()` 时抛出 `ConnectionResetError`，receiver 线程直接退出，导致后续收不到任何数据包。

**根因:** Windows 特有行为——当 UDP `sendto()` 发往一个不可达的端口时，对端返回 ICMP Port Unreachable，Windows 会将此错误传递到**同一 socket 的下一次 `recvfrom()`**，以 `ConnectionResetError` (errno 10054) 形式抛出。测试中 `esp32_port=0`，keepalive 线程向端口 0 发送 HELO，触发了此行为。

**解决方案:** 在 `_receiver_loop` 中单独捕获 `ConnectionResetError` 并 `continue`，不退出循环：
```python
except ConnectionResetError:
    # Windows: UDP ICMP port-unreachable triggers this on next recvfrom
    continue
```

**知识点:** Linux 上 UDP 不会出现此问题，因为 Linux 默认不将 ICMP 错误传递给未连接的 UDP socket。这是 Windows Winsock 的特殊行为，在编写跨平台 UDP 代码时必须注意。

---

### 问题 2: Python 3.14 不兼容 funasr_onnx

**现象:** `pip install funasr_onnx==0.4.1` 失败，报错 `Failed building wheel for onnx` 和 `kaldi-native-fbank`。

**根因:** 系统默认 Python 为 3.14.3（非常新），`onnxruntime` 和 `kaldi-native-fbank` 的预编译 wheel 尚未覆盖 Python 3.14，需要从源码编译，而源码编译在 Windows 上因路径长度限制（`error: could not create '...\test_data_set_0': 文件名或扩展名太长`）失败。

**解决方案:** 使用 `uv venv --python 3.11` 创建 Python 3.11 虚拟环境。3.11 有预编译的 wheel，`uv pip install -r requirements.txt` 一次成功。

**额外发现:** `funasr_onnx` 的 `__init__.py` 无条件 `from .sensevoice_bin import SenseVoiceSmall`，而 `sensevoice_bin.py` 依赖 `import torch`。即使项目只使用 ONNX 推理路线，也必须安装 PyTorch。使用 CPU 版（109MB）即可：
```bash
uv pip install torch --index-url https://download.pytorch.org/whl/cpu
```

**知识点:** 使用 `uv python list` 可以查看系统已安装的所有 Python 版本。uv 在创建 venv 时如果本地没有指定版本会自动下载。优先选择已有本地安装的版本可以避免下载等待。

---

### 问题 3: 默认音频设备是虚拟线缆

**现象:** ASR 识别结果完全不准确——说"今天天气真好"识别为"没有没有有没有没有异议"。麦克风模式和 UDP 模式都有问题。

**排查过程:**
1. 分析 `logs/recent.wav`：文件只有 0.04 秒，RMS=-96.9dB，Peak=-90.3dB，**100% 静音**
2. 用 `sounddevice.query_devices()` 列出设备：
   - `#0`: Microsoft 声音映射器 - Input（真实麦克风）
   - `#1`: CABLE Output (VB-Audio Virtual) **[DEFAULT]**（虚拟线缆）
3. 默认设备 #1 是 VB-Audio 虚拟线缆，没有真实音频输入，录到的全是静音

**解决方案:** 在 Windows 声音设置中将默认录音设备改回真实麦克风。或在 `config.json` 中指定设备编号：
```json
{"audio": {"device": 0}}
```

**知识点:**
- FunASR 对静音音频不会返回空结果，而是"幻觉"出文字，这是 ASR 模型的已知行为
- 判断录音是否有效：检查 WAV 文件的 RMS 值，正常语音应 > -40dB，< -80dB 基本是静音
- 可用如下代码快速检查录音质量：
```python
import wave, numpy as np
with wave.open('logs/recent.wav', 'rb') as wf:
    data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    rms = np.sqrt(np.mean(data.astype(float)**2))
    print(f'RMS={rms:.0f}, RMS_dB={20*np.log10(rms/32767):.1f}dB')
```

---

### 问题 4: F2 热键按住导致录音碎片化

**现象:** 按住 F2 说"今天天气真不错"，结果被切分为 22 个碎片：`"今天的"` → `"天气好"` → `"嗯"` → `"车了"`。每个碎片只有不到 0.5 秒的音频。

**根因:** Windows 键盘重复机制。按住按键时，系统每隔约 30ms 产生一个 keydown 事件。`keyboard.add_hotkey()` 和 `keyboard.on_press_key()` 都会响应每个 keydown，导致 `_toggle()` 被快速连续调用：start → stop → start → stop → ...，录音被反复中断。原有的 0.2 秒去抖不够——按住按键时事件频率远高于 5Hz。

**尝试过的方案:**
1. **增大去抖间隔** — 不可行，会影响正常操作的响应速度
2. **Press-to-talk 模式**（按住录音，松开停止）— 可行但用户不喜欢
3. **`on_release_key` 触发切换** ✅ — 最终方案

**解决方案:** 改用 `keyboard.on_release_key("f2", callback)`，只在**松开 F2 时**触发一次。按住 F2 不会产生 release 事件，所以完全不会重复触发。同时 `_toggle()` 内部检查 `worker.is_running` 实现幂等保护。

**知识点:**
- Windows 键盘重复：按住按键 → 延迟约 250ms 后开始以约 30Hz 频率持续产生 keydown 事件
- `keyboard` 库的三种注册方式的区别：
  - `add_hotkey(key, callback)` — 响应 keydown，受键盘重复影响
  - `on_press_key(key, callback)` — 响应 keydown，同样受键盘重复影响
  - `on_release_key(key, callback)` — 响应 keyup，每次物理按键只触发一次
- 对于"按一次切换状态"的场景，`on_release_key` 是唯一可靠的选择

---

### 问题 5: 最初设计的流式/VAD 模式被移除

**原始设计:** UDP 模式使用 VAD（Voice Activity Detection）自动切分语句，5 秒滚动窗口持续转录，不需要 F2 热键。

**为什么移除:**
1. `funasr_onnx` 的 VAD 模型加载失败（`No module named 'funasr_onnx'` 时 VAD 也无法工作）
2. 流式 VAD 增加了大量复杂度（`_streaming_capture_loop`、窗口管理、自动提交）
3. 用户更习惯手动控制录音开始/停止的方式

**最终方案:** UDP 模式和麦克风模式完全一致，统一使用 F2 热键控制。简化了代码，减少了维护负担。

---

## 四、关键知识点汇总

### 4.1 ESP32 UDP 音频协议

| 项目 | 值 |
|------|-----|
| 包格式 | `[seq:4B 小端序 uint32][PCM:640B]` = 644 字节/包 |
| 音频参数 | 16kHz、16bit 有符号整型、单声道 |
| 包率 | 50 包/秒（每包 20ms 音频） |
| 握手 | 客户端向 ESP32 发送 `HELO`（4 字节 ASCII） |
| 保活 | ESP32 在 5 秒内未收到 HELO 则断开客户端 |
| 热点 | SSID `ESP32-MIC`，密码 `12345678`，IP `192.168.4.1` |
| UDP 端口 | 6000（ESP32 监听，客户端也监听） |

### 4.2 文件改动总览

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/audio_source.py` | 新建 | AudioSource 抽象基类 |
| `app/udp_audio_source.py` | 新建 | UDP 接收器 + HELO 握手 + 保活 + Windows 兼容 |
| `app/audio_capture.py` | 修改 | 继承 AudioSource |
| `app/transcribe.py` | 修改 | 支持注入 AudioSource |
| `app/config.py` | 修改 | 新增 UDP 配置字段 |
| `app/__init__.py` | 修改 | 导出 AudioSource、UDPAudioSource |
| `main.py` | 修改 | --udp 参数 + on_release_key 热键 + 录音状态反馈（提示音/浮窗） |
| `tests/test_audio_source.py` | 新建 | ABC 测试（3 tests） |
| `tests/test_udp_audio_source.py` | 新建 | UDP 收包测试（5 tests） |
| `tests/test_e2e_udp_streaming.py` | 新建 | 端到端集成测试（2 tests） |

### 4.3 依赖安装注意事项

| 包 | 版本 | 说明 |
|-----|------|------|
| `funasr_onnx` | 0.4.1 | ONNX 推理，仅兼容 Python ≤ 3.12 |
| `onnxruntime` | 1.24.4 | ONNX 运行时，Python 3.14 无预编译 wheel |
| `torch` | CPU 版 | funasr_onnx 间接依赖，仅 109MB |
| `kaldi-native-fbank` | 1.22.3 | 音频特征提取，Python 3.14 编译失败 |

### 4.4 配置参考

`config.json` 示例（可选，放在项目根目录）：
```json
{
    "audio": {
        "device": 0,
        "esp32_host": "192.168.4.1",
        "esp32_port": 6000,
        "listen_port": 6000
    },
    "hotkeys": {
        "toggle": "f2"
    }
}
```
使用方式：`python main.py --config config.json --udp 192.168.4.1:6000`

### 4.5 调试技巧

**检查音频设备：**
```python
import sounddevice as sd
print(sd.query_devices())  # 列出所有设备
print(sd.default.device)   # 默认设备编号 [input, output]
```

**分析录音文件质量：**
```python
import wave, numpy as np
with wave.open('logs/recent.wav', 'rb') as wf:
    data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    rms = np.sqrt(np.mean(data.astype(float)**2))
    dur = wf.getnframes() / wf.getframerate()
    print(f'duration={dur:.2f}s  RMS={rms:.0f}  RMS_dB={20*np.log10(max(rms,1)/32767):.1f}dB')
    # 正常语音: > -40dB | 安静环境: -50~-60dB | 静音/虚拟设备: < -80dB
```

**测试 UDP 连通性：**
```python
import socket, struct, numpy as np
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(b"HELO", ("192.168.4.1", 6000))  # 握手
data, addr = sock.recvfrom(2048)               # 应收到 644 字节
seq = struct.unpack_from("<I", data, 0)[0]
pcm = np.frombuffer(data[4:644], dtype=np.int16)
print(f"seq={seq}, samples={len(pcm)}, rms={np.sqrt(np.mean(pcm.astype(float)**2)):.0f}")
```
