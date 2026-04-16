# DashScope 云端 ASR 集成设计

## 概述

将阿里云 DashScope Paraformer 云端语音识别集成到 vocotype，作为本地 FunASR ONNX 引擎的替代方案。用户通过配置字段切换本地/云端后端。云端 ASR 复用用户已有的 DashScope API key（Qwen 同款）。

## 动机

- 本地 Paraformer-large ONNX 受限于 CPU 算力，云端版使用更大模型、准确率更高
- 云端热词/领域适配能力更强
- 用户已有 DashScope API key（`sk-` 格式）

## 范围

**本次包含：**
- DashScope Paraformer 云端 ASR 集成（文件识别模式）
- 配置驱动的后端切换（`asr.backend: "local" | "cloud"`）
- 新建 `app/cloud_asr.py` 模块封装 DashScope Recognition SDK
- F2 手动录音和 VAD 自动检测两种模式均支持

**本次不含：**
- 云端声纹识别（DashScope 无声纹验证 API）
- 实时流式模式（文件模式验证通过后再做）
- 网络异常时自动降级到本地

## 配置

在 `app/config.py` 的 `DEFAULT_CONFIG` 中新增：

```python
"asr": {
    "backend": "local",          # "local" | "cloud"
    # ... 现有字段不变 ...
},
"cloud_asr": {
    "provider": "dashscope",
    "api_key": "",               # sk-xxx，也可通过环境变量设置
    "model": "paraformer-realtime-v2",
    "format": "pcm",
    "sample_rate": 16000,
    "disfluency_removal": False,
},
```

### API Key 解析顺序

1. `config["cloud_asr"]["api_key"]`（config.json 中配置）
2. 环境变量 `DASHSCOPE_API_KEY`
3. 两者都没有：启动时报错，提示用户配置 key

## 架构

### 新模块：`app/cloud_asr.py`

```
class CloudASR:
    __init__(config: dict)
        - 读取 cloud_asr 配置段
        - 解析 API key（配置 -> 环境变量 -> 报错）
        - 存储参数；此时不创建 Recognition 实例

    transcribe_file(wav_path: str) -> dict
        - 创建 Recognition 实例和 RecognitionCallback
        - 调用 Recognition.call(file=wav_path) 同步识别
        - 从 on_event 回调中收集识别结果句子
        - 返回统一格式的结果字典：
          {"success": bool, "text": str, "raw_text": str,
           "confidence": float, "duration": float, "error": str|None}

    # 未来：流式方法
    start_stream() -> None
    send_frame(pcm_bytes: bytes) -> None
    stop_stream() -> dict
```

关键设计决策：
- **返回格式统一**：与 `FunASRServer.transcribe_audio()` 返回相同结构的字典，上层调用者无需修改
- **回调转同步**：`RecognitionCallback` 的 `on_event/on_complete` 将结果收集到列表中；`on_complete` 触发 `threading.Event`；`transcribe_file` 等待该事件
- **错误包装**：网络超时、API 错误统一包装为 `{"success": False, "error": "..."}`
- **无持久连接**：每次 `transcribe_file` 调用创建新的 Recognition 实例（无状态、简单）

### 集成点

#### `app/transcribe.py`（F2 手动录音）

`TranscriptionWorker.__init__` 中：
- 读取 `config["asr"]["backend"]`
- `"local"`：照旧初始化 `FunASRServer`
- `"cloud"`：改为初始化 `CloudASR`，跳过 FunASR 模型加载

`_transcribe_once(samples)` 中：
- `"local"`：`self.fun_server.transcribe_audio(path)`（不变）
- `"cloud"`：`self.cloud_asr.transcribe_file(path)`
- 后续逻辑（结果构造、on_result 回调）不变

#### `app/vad_worker.py`（VAD 持续监听）

同 transcribe.py 的模式：
- `__init__`：根据 backend 条件初始化 FunASRServer 或 CloudASR
- `_transcribe_once`：路由到本地或云端转写
- 其他全部不变（VAD、声纹、KWS）

### 不变的部分

- `TranscriptionResult` dataclass
- `on_result` 回调接口
- 声纹识别（本地 CAM++）
- VAD 检测（FireRedVAD）
- KWS 关键词检测（sherpa-onnx）
- 音频采集 / 音频源抽象
- 输出 / 键盘模拟

## 启动行为

| backend | 加载 FunASR | 加载 CloudASR | 需要 API key |
|---------|------------|--------------|-------------|
| `local` | 是 | 否 | 否 |
| `cloud` | 否 | 是 | 是 |

云端模式完全跳过 FunASR 模型加载，启动更快、内存占用更低。

## 依赖

- `dashscope` >= 1.25.0（已安装 v1.25.17）
- 无新增系统依赖

## API Key 安全

- 不硬编码、不提交到 git
- `config.json` 已在 `.gitignore` 中
- 环境变量作为替代方案

## 后续迭代（本次不做）

- **VAD 流式模式**：在 `_listen_loop` 中，语音开始时 `start_stream()`，每帧 `send_frame()`，语音结束时 `stop_stream()` 拿结果，延迟更低
- **自动降级**：默认用云端，网络异常自动降级到本地
- **云端声纹识别**：如果 DashScope 未来推出声纹验证 API
- **其他厂商**：Azure Speech、Whisper API，通过同样的配置模式（`cloud_asr.provider`）接入

## 文件变更汇总

| 文件 | 变更 |
|------|------|
| `app/cloud_asr.py` | **新建** — CloudASR 封装类 |
| `app/config.py` | 新增 `asr.backend` 和 `cloud_asr` 配置段 |
| `app/transcribe.py` | 条件初始化 + `_transcribe_once` 路由 |
| `app/vad_worker.py` | 条件初始化 + `_transcribe_once` 路由 |
