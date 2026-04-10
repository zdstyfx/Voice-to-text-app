# 无监督说话人分离（Speaker Diarization）设计文档

## 概述

基于现有 CAM++ 模型新增无监督说话人分离模式（diarize）：不需要预注册声纹，VAD 检测到语音后自动聚类，标注"说话人1""说话人2"等。适用于会议、访谈等多人场景。

同时删除旧的"实时注册模式"（enroll）— VAD 自动采集声纹样本的功能。保留声纹注册（CLI/UI手动注册）、identify 模式、filter 模式。

## 变更范围

| 内容 | 操作 |
|------|------|
| `app/speaker.py` — `SpeakerProcessor` 全部功能 | **保留** |
| `app/speaker_db.py` — `SpeakerDB` | **保留** |
| `app/speaker_enroll.py` — 注册 CLI | **保留** |
| `app/enrollment_ui.py` — 注册交互 UI | **保留** |
| identify 模式（标注已知说话人） | **保留** |
| filter 模式（白名单过滤） | **保留** |
| enroll 模式（VAD 自动采集声纹） | **删除** |
| diarize 模式（无监督说话人分离） | **新增** |

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 聚类算法 | 在线增量聚类 | 实时标注，符合转写交互体验 |
| 与声纹库关系 | 完全独立 | diarize 不依赖 SpeakerDB，是纯内存聚类 |
| 聚类状态 | 纯内存 | 每次会话重置，无需持久化 |
| 改名支持 | 需要 | 转写结束后可在 Web UI 给说话人改名 |

## 架构

### 新增组件

#### `app/speaker_cluster.py` — 在线说话人聚类

```python
@dataclass
class ClusterEntry:
    embeddings: list[np.ndarray]  # 所有 embedding（用于重算质心）
    centroid: np.ndarray          # L2 归一化质心
    count: int                    # 分配到该 cluster 的语音段数

class SpeakerCluster:
    def __init__(self, threshold: float = 0.45):
        self._clusters: dict[str, ClusterEntry] = {}
        self._threshold = threshold
        self._counter = 0

    def assign(self, embedding: np.ndarray) -> str:
        """核心方法：分配 embedding 到已有 cluster 或创建新 cluster"""
        # 1. L2 归一化 embedding
        # 2. 与所有 cluster 质心计算余弦相似度
        # 3. best_score >= threshold → 归入该 cluster，增量更新质心
        # 4. best_score < threshold → 新建 "说话人{N+1}"

    def rename(self, old_name: str, new_name: str) -> bool:
        """改名：如 "说话人1" → "张三" """

    def reset(self) -> None:
        """清空所有 cluster（新会话开始时调用）"""

    def get_speakers(self) -> list[dict]:
        """返回所有说话人信息：[{name, count}]"""
```

**聚类逻辑**：
- 每段语音提取 192 维 embedding（复用 `SpeakerProcessor.extract_embedding()`）
- 与所有 cluster 质心计算余弦相似度
- 最高分 >= `threshold`（默认 0.45）→ 归入该 cluster，用新 embedding 更新质心
- 最高分 < `threshold` → 创建新 cluster，命名 "说话人{N+1}"
- 质心更新采用增量平均 + L2 归一化

### 删除内容

#### `app/vad_worker.py` — 删除 enroll 分支

删除 `_submit_speech()` 中的 enroll 模式分支（lines 239-263）：
```python
# 删除这段
if self._speaker_mode == "enroll" and self._speaker_processor:
    ...
    return
```

删除构造函数中的 enroll 相关状态：
- `_enroll_target`
- `_enroll_count`
- `_enroll_samples`

#### `app/config.py` — 删除 enroll 配置项

删除：`enroll_target`, `enroll_samples`, `min_enroll_samples`

保留其余所有 speaker 配置项（enabled, mode, model, threshold, db_path, auto_learn, whitelist, incremental_learn, incremental_margin, max_embeddings）。

#### `main.py` — 删除实时注册模式入口

声纹选择子菜单从：
```
[1] 关闭
[2] 识别模式（标注说话人）
[3] 过滤模式（只转录指定人）
[4] 实时注册模式（VAD自动采集声纹）
```

变为：
```
[1] 关闭
[2] 识别模式（标注说话人）
[3] 过滤模式（只转录指定人）
[4] 说话人分离（自动区分不同说话人）
```

#### Web UI — 删除 enroll 相关

- `app/web/pages/settings.py`：speaker mode 下拉框移除 "enroll" 选项，新增 "diarize" 选项
- `app/web/pages/speakers.py`：删除实时注册进度跟踪（enrollment progress），保留手动注册功能

### 新增内容

#### `app/vad_worker.py` — 新增 diarize 分支

在 `_submit_speech()` 中新增 diarize 模式：

```python
elif self._speaker_mode == "diarize":
    try:
        embedding = self._speaker_processor.extract_embedding(combined)
        speaker_id = self._speaker_cluster.assign(embedding)
        speaker_confidence = ...  # assign 返回的相似度分数
    except Exception:
        speaker_id = None
```

构造函数新增 `speaker_cluster: Optional[SpeakerCluster]` 参数。

#### Web UI — 说话人分离支持

**`app/web/pages/settings.py`**：
- speaker mode 下拉框新增 "说话人分离" 选项

**`app/web/pages/speakers.py`**：
- 新增区域：显示当前会话的聚类说话人列表（从 SpeakerCluster 读取）
- 每个说话人旁边有改名按钮，点击弹出输入框

**`app/web/pages/transcribe.py`**：
- 已有 speaker badge 显示逻辑自动适用（显示 "说话人1" 而非 "张三"）
- 改名后刷新已显示的转写记录中的说话人名称

**`app/web/state.py`**：
- 新增 `speaker_cluster: Optional[SpeakerCluster]` 引用

## 数据流

```
音频帧 → VAD 检测语音结束
  → extract_embedding(audio)        # 192 维向量
  → SpeakerCluster.assign(emb)      # 在线聚类
    ├─ 匹配已有 cluster → "说话人1"，更新质心
    └─ 无匹配 → 新建 "说话人3"
  → ASR 转录
  → TranscriptionResult(text=..., speaker="说话人1", speaker_confidence=0.72)
  → Web UI 显示 [说话人1] 转录文本
```

## 改名流程

```
Web UI 说话人列表 → 点击 "说话人1" 旁的改名按钮
  → 弹出输入框，输入 "张三"
  → SpeakerCluster.rename("说话人1", "张三")
  → 刷新转写记录中所有 "说话人1" → "张三"
```

## 边界情况

| 场景 | 处理 |
|------|------|
| CAM++ 模型加载失败 | 警告日志，转写继续但无说话人标注 |
| embedding 提取失败（音频太短）| speaker 设为 None，不阻塞转写 |
| 只有一个人说话 | 全部归入 "说话人1"，正常工作 |
| 停止/重新开始转写 | SpeakerCluster.reset()，编号重新开始 |
| 阈值太低导致合并 | 用户可在设置页调整 threshold |
| 阈值太高导致拆分 | 同上 |
