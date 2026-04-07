# 声纹识别集成设计

## 概述

在现有 VAD 智能语音转录系统中集成声纹识别功能，基于 CAM++ 模型（ModelScope），实现说话人识别（标注）和说话人过滤（只转录指定人）两种模式。

## 需求

- **双功能**：说话人识别（在转录文本前标注说话人） + 说话人过滤（只转录白名单内的人），可配置选择
- **双注册**：手动录制样本注册常用用户 + 自动聚类学习会议中的新说话人
- **离线优先**：默认本地CPU推理，可扩展云端API
- **数据流位置**：VAD 之后、ASR 之前（过滤模式可跳过非目标人的ASR，省计算）

## 模型选型

**CAM++ via ModelScope** (`iic/speech_campplus_sv_zh-cn_16k-common`)

| 属性 | 值 |
|------|------|
| 参数量 | 7.2M |
| 模型大小 | ~29MB |
| Embedding维度 | 192 |
| 中文EER | 4.32% (CN-Celeb, 20万说话人训练) |
| 许可证 | Apache 2.0 |

选型理由：
- 项目已依赖 `modelscope` + `torch`，零新增依赖
- 20万中文说话人训练数据，中文声纹精度最高
- FunASR 生态内置工具函数（sv_chunk、embedding提取）
- 模型下载方式和现有ASR模型完全一致

## 架构设计

### 数据流

```
                         ┌─────────────────────────────┐
                         │     SpeakerDB (本地JSON)      │
                         │  张三: [emb1, emb2, ...]      │
                         │  李四: [emb1, emb2, ...]      │
                         │  auto_001: [emb1, ...]        │
                         └──────────┬──────────────────┘
                                    │
音频帧 → VAD检测语音段 → SpeakerProcessor → 决策分支:
                              │
                    ┌─────────┴──────────┐
                    │                    │
              [识别模式]            [过滤模式]
              匹配说话人ID          匹配白名单?
                    │                    │
                    │               是 → ASR转录 → "张三: ..."
                    │               否 → 丢弃，跳过ASR
                    │
              ASR转录 → "[张三] 今天开会..."
```

### 新增组件

| 组件 | 文件 | 职责 |
|------|------|------|
| SpeakerProcessor | `app/speaker.py` | CAM++ embedding提取 + 余弦相似度匹配 |
| SpeakerDB | `app/speaker_db.py` | 声纹库管理（注册/删除/查询/持久化） |
| 注册CLI | `app/speaker_enroll.py` | 录制样本注册新说话人的独立脚本 |

## 详细设计

### SpeakerProcessor (`app/speaker.py`)

```python
class SpeakerProcessor:
    def __init__(self, config):
        # 加载 CAM++ 模型 (ModelScope)
        # 加载 SpeakerDB

    def extract_embedding(self, audio: np.ndarray) -> np.ndarray:
        """从音频段提取 192维 speaker embedding"""

    def identify(self, audio: np.ndarray) -> SpeakerResult:
        """识别模式：返回最匹配的说话人 + 置信度
        1. 提取 embedding
        2. 和 DB 中所有人做余弦相似度
        3. 最高分 >= threshold → 返回匹配的人名
        4. 最高分 < threshold + auto_learn=True → 创建新说话人 "speaker_001"
        5. 最高分 < threshold + auto_learn=False → 返回 "unknown"
        """

    def should_transcribe(self, audio: np.ndarray) -> tuple[bool, str]:
        """过滤模式：判断是否在白名单中，返回 (是否转录, 说话人名)"""
```

返回结构：
```python
@dataclass
class SpeakerResult:
    speaker_id: str        # "张三" | "speaker_001" | "unknown"
    confidence: float      # 余弦相似度 0~1
    is_known: bool         # 是否匹配到已注册说话人
```

### SpeakerDB (`app/speaker_db.py`)

存储格式 — `speaker_db.json`：
```json
{
  "speakers": {
    "张三": {
      "embeddings": [[0.12, -0.34, ...], ...],
      "centroid": [0.15, -0.31, ...],
      "registered_at": "2026-04-07T10:00:00",
      "sample_count": 3
    }
  },
  "auto_speakers": {
    "speaker_001": { "..." : "..." }
  }
}
```

关键方法：
- `enroll(name, embedding)` — 注册/追加embedding，更新centroid
- `remove(name)` — 删除说话人
- `match(embedding, threshold)` — 返回最近匹配
- `rename(old, new)` — 给自动聚类的说话人赋名
- `save()` / `load()` — JSON持久化

### 配置扩展 (`app/config.py`)

```python
"speaker": {
    "enabled": False,           # 总开关
    "mode": "identify",         # "identify" | "filter" | "off"
    "model": "iic/speech_campplus_sv_zh-cn_16k-common",
    "threshold": 0.65,          # 余弦相似度阈值
    "db_path": "speaker_db.json",
    "auto_learn": False,        # 自动聚类学习新说话人
    "whitelist": [],            # 过滤模式的白名单 ["张三", "李四"]
}
```

### vad_worker.py 改动

在 `_submit_speech()` 中插入声纹判断：

```python
def _submit_speech(self) -> None:
    combined = np.concatenate(self._speech_buffer)
    self._speech_buffer.clear()

    # === 新增：声纹识别 ===
    if self._speaker_processor:
        if self._speaker_mode == "filter":
            should_transcribe, speaker_id = self._speaker_processor.should_transcribe(combined)
            if not should_transcribe:
                logger.info("VAD: 非白名单说话人 (%s)，跳过转录", speaker_id)
                return
        elif self._speaker_mode == "identify":
            result = self._speaker_processor.identify(combined)
            # speaker_id 附加到转录结果中

    # 原有逻辑：提交到转录队列
    self._transcription_queue.put_nowait(combined)
```

F2模式的 `transcribe.py` 同理，在 `stop()` 合并音频后、提交转录前插入。

### TranscriptionResult 扩展

```python
@dataclass
class TranscriptionResult:
    text: str
    raw_text: str
    duration: float
    inference_latency: float
    confidence: float
    error: Optional[str] = None
    speaker: Optional[str] = None           # 新增
    speaker_confidence: Optional[float] = None  # 新增
```

### main.py 交互流程

在现有选择之后新增声纹选择：

```
  声纹识别:
  [1] 关闭（不使用声纹）
  [2] 识别模式（标注说话人）
  [3] 过滤模式（只转录指定人）
  输入 1/2/3:
```

过滤模式时显示已注册说话人供选择白名单。

文本输出格式：
- 识别模式: `[张三] 今天下午三点开会`
- 过滤模式: 正常文本（已过滤非目标人）

### 注册CLI (`app/speaker_enroll.py`)

```bash
# 录制注册
python -m app.speaker_enroll --name "张三" --duration 10

# 从文件注册
python -m app.speaker_enroll --name "张三" --audio samples/zhangsan.wav
```

### 模型加载

CAM++ 与 FunASR、FireRedVAD 并行加载：

```python
threads = [
    Thread(target=load_funasr),
    Thread(target=load_fireredvad),
    Thread(target=load_campplus),      # 声纹开启时
]
```

预计增加启动时间 ~1-2秒。

### 错误处理

- 声纹模型加载失败 → 警告日志，退化为无声纹模式（不阻塞正常转录）
- `speaker_db.json` 不存在 → 自动创建空库
- 过滤模式但无已注册声纹 → 提示用户先注册，退化为识别模式
- embedding 提取失败（音频太短等） → 跳过声纹判断，直接走ASR

## 文件改动汇总

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `app/speaker.py` | 新建 | SpeakerProcessor + CAM++推理 |
| `app/speaker_db.py` | 新建 | 声纹库CRUD + JSON持久化 |
| `app/speaker_enroll.py` | 新建 | 注册CLI脚本 |
| `app/config.py` | 修改 | 新增 `speaker` 配置段 |
| `app/vad_worker.py` | 修改 | `_submit_speech()` 插入声纹判断 |
| `app/transcribe.py` | 修改 | `TranscriptionResult` 加字段 + `stop()` 插入声纹 |
| `main.py` | 修改 | 新增声纹交互选择 + 结果输出格式 |
