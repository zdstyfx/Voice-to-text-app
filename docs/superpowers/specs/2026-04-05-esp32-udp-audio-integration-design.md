# ESP32 UDP 音频集成设计

## 概述

将 ESP32-S3 无线麦克风作为 UDP 音频源集成到 VocoType，实现从 ESP32 硬件直接实时语音转文字，输入到任意 Windows 应用。

## 需求

- ESP32 固件保持不变
- VocoType 通过 UDP 接收 ESP32 发来的 16kHz/16bit/Mono PCM 音频
- 实时流式转写，基于 VAD 自动切分语句
- 转写文字通过 SendInput 自动输入到当前焦点应用
- 通过 `--udp` 命令行参数或配置文件手动指定连接

## 架构

```
┌─────────────┐        UDP (644B/包)         ┌──────────────────────┐
│   ESP32-S3  │ ──────────────────────────►   │   UDPAudioSource     │
│  (不改动)    │   [seq:4B][PCM:640B]         │   监听 0.0.0.0:6000  │
│             │                               │   ├─ 剥离序列号头     │
│  AP: 192.168.4.1                            │   ├─ np.int16 帧     │
│  UDP 端口 6000                              │   └─► queue.put()    │
└─────────────┘                               └──────────┬───────────┘
                                                         │ queue.Queue[np.ndarray]
                                                         ▼
                                              ┌──────────────────────┐
                                              │  TranscriptionWorker │
                                              │  _capture_loop()     │
                                              │   ├─ queue.get()     │
                                              │   ├─ buffer.append() │
                                              │   └─ VAD 自动切分     │
                                              └──────────┬───────────┘
                                                         │ np.ndarray (完整语句)
                                                         ▼
                                              ┌──────────────────────┐
                                              │  FunASR (本地推理)    │
                                              │  Paraformer + 标点   │
                                              └──────────┬───────────┘
                                                         │ 文字
                                                         ▼
                                              ┌──────────────────────┐
                                              │  Windows SendInput   │
                                              │  → 当前焦点应用       │
                                              └──────────────────────┘
```

## ESP32 协议（现有，不改动）

- **包格式**：`[seq:4B 小端序 uint32][PCM:640B]` = 每包 644 字节
- **音频参数**：16kHz、16bit 有符号、单声道、20ms/包、50 包/秒
- **握手**：客户端向 ESP32 UDP 端口 6000 发送 "HELO"（4 字节）
- **保活**：ESP32 在 5 秒内未收到 HELO 则断开客户端
- **热点**：SSID "ESP32-MIC"，密码 "12345678"，IP 192.168.4.1

## 组件设计

### 1. AudioSource 抽象基类（`app/audio_source.py` — 新建）

定义音频源接口的抽象基类：

```python
class AudioSource(ABC):
    @property
    @abstractmethod
    def queue(self) -> queue.Queue[np.ndarray]: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def flush(self) -> None: ...
```

### 2. AudioCapture 重构（`app/audio_capture.py` — 修改）

- 继承 `AudioSource`
- 不改变任何逻辑，仅添加 `class AudioCapture(AudioSource):`

### 3. UDPAudioSource（`app/udp_audio_source.py` — 新建）

接收 ESP32 的 UDP 音频流，填入标准 queue 接口。

**构造参数**：
- `esp32_host: str` — ESP32 IP（默认 "192.168.4.1"）
- `esp32_port: int` — ESP32 UDP 端口（默认 6000）
- `listen_port: int` — 本地监听端口（默认 6000）
- `sample_rate: int` — 16000
- `block_ms: int` — 20
- `queue_size: int` — 200

**线程模型**：
| 线程 | 职责 |
|------|------|
| `_receiver_thread` | `recvfrom()` 循环 → 解析数据包 → `queue.put_nowait()` |
| `_keepalive_thread` | 每 2 秒向 ESP32 发送 "HELO" 保活 |

**数据包解析**：
- 接收 644 字节数据包
- 提取前 4 字节为 uint32 小端序序列号（用于丢包检测）
- 提取第 4-644 字节为 PCM 数据 → `np.frombuffer(data[4:], dtype=np.int16).copy()`
- 序列号不连续时记录 warning 日志

**生命周期**：
- `start()`：绑定 socket，发送初始 HELO，启动接收线程 + 保活线程
- `stop()`：设置 running=False，关闭 socket，join 线程
- `flush()`：清空队列

### 4. TranscriptionWorker 修改（`app/transcribe.py` — 修改）

**依赖注入**：
- 在 `__init__` 中增加可选参数 `audio_source: AudioSource = None`
- 如果提供了 audio_source，使用它替代创建 `AudioCapture`

**流式模式**：
- 新增 `streaming: bool` 标志（使用 UDP 源时为 True）
- 当 streaming=True 时：
  - 自动设置 `_recording` 事件（始终录制）
  - 启用 VAD（`use_vad=True`）自动切分语句
  - 使用滚动窗口：每积累 N 秒音频或检测到 VAD 静音段时提交转录
  - 禁用 F2 热键切换（不需要）

### 5. 配置修改（`app/config.py` — 修改）

在 `DEFAULT_CONFIG["audio"]` 中新增：
```python
"type": "microphone",      # 或 "udp"
"esp32_host": "192.168.4.1",
"esp32_port": 6000,
"listen_port": 6000,
```

### 6. 命令行修改（`main.py` — 修改）

新增 `--udp` 参数：
```bash
python main.py --udp 192.168.4.1:6000
```

该参数会覆盖 `audio.type` 为 "udp"，并设置 `esp32_host`/`esp32_port`。

## 错误处理

| 场景 | 处理方式 |
|------|---------|
| ESP32 未启动/不可达 | 持续发送 HELO，日志提示 "等待 ESP32 连接..." |
| UDP 丢包 | 记录 warning 日志（含丢失包数），不重传 |
| ESP32 WiFi 断连 | 保活线程继续运行，恢复后自动重连 |
| 队列满 | 丢弃最新帧，记录 warning 日志 |
| 畸形数据包（<644B） | 丢弃并记录 warning 日志 |

## 文件改动汇总

| # | 文件 | 操作 | 说明 |
|---|------|------|------|
| 1 | `app/audio_source.py` | 新建 | `AudioSource` 抽象基类 |
| 2 | `app/audio_capture.py` | 修改 | 继承 `AudioSource` |
| 3 | `app/udp_audio_source.py` | 新建 | UDP 接收器 + HELO 握手 + 保活 |
| 4 | `app/transcribe.py` | 修改 | 注入 AudioSource；增加流式模式 |
| 5 | `app/config.py` | 修改 | 新增 UDP 配置字段 |
| 6 | `main.py` | 修改 | 新增 `--udp` 命令行参数，条件初始化 |

## 使用方法

```bash
# 1. 将 Windows 连接到 ESP32-MIC WiFi 热点
# 2. 以 UDP 模式启动 VocoType
python main.py --udp 192.168.4.1:6000

# 3. 对着 ESP32 麦克风说话 → 文字自动输入到当前应用
# 4. Ctrl+C 退出
```

## 测试计划

1. 单元测试：用模拟 UDP 数据包测试 UDPAudioSource
2. 集成测试：ESP32 → UDPAudioSource → 验证队列数据
3. 端到端测试：ESP32 → VocoType → 验证文字输出
4. 压力测试：持续流式传输稳定性
