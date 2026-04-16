# DashScope 实时流式 ASR 设计

## 背景

当前云端 ASR（DashScope Paraformer）使用批处理模式：VAD 检测语音段 → 攒完整音频 → 写 WAV 文件 → `Recognition.call()` 一次性识别。延迟 = 语音结束 + 800ms 合并间隔 + 推理时间。

目标：云端模式下改为实时流式识别，音频帧直接送入 WebSocket 连接，边说边出字，显著降低感知延迟。

## 范围

- 仅改造云端 DashScope 路径
- 本地 FunASR ONNX 批处理保持不变
- F2 手动录音模式不变
- KWS / 声纹识别逻辑不变

## 架构

### 现有批处理流程（本地 FunASR，不变）

```
麦克风帧 → VAD 检测边界 → 攒完整段 → 写 WAV → Paraformer 一次性识别 → type_text() 输出
```

### 新流式流程（云端 DashScope）

```
麦克风帧 → CloudASR.send_frame(pcm_bytes)
                  ↓ WebSocket
           DashScope paraformer-realtime-v2
                  ↓
           on_event(中间结果) → 终端覆盖刷新当前行
           on_event(最终结果) → 确认句子，换行
```

关键变化：云端流式模式下跳过 VAD 分段逻辑。DashScope 服务端自带 VAD 和断句能力，客户端只需持续送帧，服务端自行判断句子边界返回 `sentence_end`。

## 模块改动

### 1. `app/cloud_asr.py` — 新增流式 API

新增方法，与现有 `transcribe_file()` 并存：

- `start_streaming(on_partial, on_sentence)` — 建立 WebSocket 连接
  - `on_partial(text: str)`: 中间结果回调（同一句话不断更新的文本）
  - `on_sentence(text: str)`: 最终结果回调（一句话确认完成）
  - 内部创建 `Recognition(model, callback=_StreamCallback(...), format="pcm", sample_rate=16000)`
  - 调用 `recognition.start()`

- `send_frame(pcm_bytes: bytes)` — 送入一帧 PCM 音频
  - 内部调用 `recognition.send_audio_frame(pcm_bytes)`
  - 输入格式：int16, 16kHz, mono 的原始 PCM 字节

- `stop_streaming()` — 结束流式识别
  - 内部调用 `recognition.stop()`
  - 等待 `on_complete` 回调确认关闭

内部新增 `_StreamCallback(RecognitionCallback)`:
- `on_event(result)`: 解析 `result.get_sentence()`
  - `RecognitionResult.is_sentence_end(sentence)` 为 True → 调用 `on_sentence(sentence["text"])`
  - 否则 → 调用 `on_partial(sentence["text"])`
- `on_error(result)`: 日志报错
- `on_complete()`: 标记会话结束

### 2. `app/vad_worker.py` — 云端流式路径

`_listen_loop` 中云端模式的帧处理逻辑改变：

- 启动时：如果 `_asr_backend == "cloud"`，调用 `cloud_asr.start_streaming(on_partial, on_sentence)`
- 每帧：直接调用 `cloud_asr.send_frame(frame.tobytes())`，跳过 VAD 分段 / 攒 buffer / 写 WAV / 转录队列
- 停止时：调用 `cloud_asr.stop_streaming()`

本地 FunASR 路径（VAD 分段 → 攒段 → 写 WAV → 批处理）完全不变。

KWS 模式下如果使用云端后端，仍走 KWS 状态机控制（idle/active 切换），active 态内的帧送流式 ASR。

### 3. `main.py` — 终端实时显示

云端流式模式使用新的输出逻辑（不走 `type_text()` 键盘注入）：

- `on_partial(text)` → `\r` + 文本 + 空格填充覆盖上一次中间结果
- `on_sentence(text)` → `\r` + 文本 + `\n` 换行确认
- 长文本超过终端宽度时：中间结果截断显示，最终结果完整输出

### 4. `app/config.py` — 微调

`cloud_asr.format` 默认值从 `"pcm"` 确认为 `"pcm"`（当前已是 pcm，无需改动，仅确认）。

## 连接生命周期与错误处理

- **启动**：选择云端模式后建立 WebSocket 连接。连接失败则报错退出
- **运行中断线**：`on_error()` 回调触发时，日志报错 + 尝试自动重连一次。重连失败则通知用户
- **正常退出**：Ctrl+C → `stop_streaming()` → 等待 `on_complete()` → 关闭连接

## DashScope 回调结果解析

`on_event(result)` 中通过 `result.get_sentence()` 获取：
- 返回值为 list 时，取最后一个 sentence
- `sentence` 字典中有 `end_time` 字段 → `is_sentence_end() == True` → 最终结果
- `sentence` 字典中无 `end_time` → 中间结果

## 不在范围内

- 本地离线流式 ASR（需要换 sherpa-onnx 流式模型，后续课题）
- 流式结果的键盘注入（中间结果频繁注入不现实）
- 流式模式 + 声纹识别联动
- 断线自动重连循环（一次重连足够）
- F2 手动录音模式的流式化

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `app/cloud_asr.py` | 修改 | 新增流式 API + `_StreamCallback` |
| `app/vad_worker.py` | 修改 | 云端模式 `_listen_loop` 直接送帧 |
| `main.py` | 修改 | 新增流式终端显示回调 |
| `app/config.py` | 确认 | `format: "pcm"` 已正确 |
