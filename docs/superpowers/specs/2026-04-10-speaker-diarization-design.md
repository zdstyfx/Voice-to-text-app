# 无监督说话人分离（Speaker Diarization）设计文档

## 概述

基于现有 CAM++ 模型实现无监督说话人分离：不需要预注册声纹，VAD 检测到语音后自动聚类，标注"说话人1""说话人2"等。适用于会议、访谈等多人场景。

同时删除旧的声纹识别功能（identify/filter/enroll 模式），只保留 diarize 模式。

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 聚类算法 | 在线增量聚类 | 实时标注，符合转写交互体验 |
| 与旧声纹库关系 | 完全独立 | 旧功能删除，新功能不依赖 SpeakerDB |
| 聚类状态 | 纯内存 | 每次会话重置，无需持久化 |
| 已注册声纹 | 删除相关功能 | identify/filter/enroll 全部移除 |
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

### 保留组件

#### `app/speaker.py` — 精简为 embedding 提取器

保留：
- `SpeakerProcessor.__init__()` — CAM++ 模型加载
- `SpeakerProcessor.extract_embedding()` — 音频 → 192 维 embedding

删除：
- `SpeakerResult` dataclass
- `identify()` 方法
- `should_transcribe()` 方法
- 所有 whitelist / incremental_learn / auto_learn 逻辑

### 删除组件

| 文件 | 操作 | 理由 |
|------|------|------|
| `app/speaker_db.py` | 删除 | 声纹库不再需要 |
| `app/speaker_enroll.py` | 删除 | 注册 CLI 不再需要 |
| `app/enrollment_ui.py` | 删除 | 注册交互 UI 不再需要 |
| `speaker_db.json` | 删除 | 声纹库数据文件不再需要 |

### 修改组件

#### `app/config.py`

精简 `speaker` 配置段：

```python
"speaker": {
    "enabled": False,
    "mode": "diarize",        # 唯一模式，保留字段是为了 on/off 控制
    "model": "iic/speech_campplus_sv_zh-cn_16k-common",
    "threshold": 0.45,        # 聚类阈值
}
```

删除：`db_path`, `auto_learn`, `whitelist`, `incremental_learn`, `incremental_margin`, `max_embeddings`, `enroll_target`, `enroll_samples`, `min_enroll_samples`

#### `app/vad_worker.py`

`_submit_speech()` 中：
- 删除 identify/filter/enroll 分支
- 新增 diarize 分支：

```python
if self._speaker_cluster and self._speaker_processor:
    try:
        embedding = self._speaker_processor.extract_embedding(combined)
        speaker_id = self._speaker_cluster.assign(embedding)
    except Exception:
        speaker_id = None
```

构造函数变化：
- 删除 `speaker_mode` 参数
- 新增 `speaker_cluster: Optional[SpeakerCluster]` 参数
- 保留 `speaker_processor: Optional[SpeakerProcessor]` 参数

#### `app/transcribe.py`

`TranscriptionResult` 保持不变 — `speaker` 和 `speaker_confidence` 字段继续使用。diarize 模式下 `speaker_confidence` 可设为聚类相似度分数。

#### `main.py`

- 删除声纹管理菜单（`[3] 声纹注册/管理`）
- 删除声纹模式选择子菜单（identify/filter/enroll）
- 简化为：转写时如果 `speaker.enabled`，自动启用 diarize

#### Web UI 改动

**`app/web/pages/settings.py`**：
- speaker mode 下拉框简化为 开/关（enabled toggle）
- 删除 whitelist 管理

**`app/web/pages/speakers.py`**：
- 删除原注册/管理功能
- 改为：显示当前会话的说话人列表（从 SpeakerCluster 读取）
- 每个说话人旁边有改名按钮

**`app/web/pages/transcribe.py`**：
- 已有 speaker badge 显示逻辑自动适用
- 改名后需要刷新已显示的转写记录中的说话人名称

**`app/web/state.py`**：
- 删除 `speaker_mode`, `speaker_whitelist` 等旧状态
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
