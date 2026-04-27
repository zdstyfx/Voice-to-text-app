# 火山引擎 Seed ASR 2.0 API 对比分析

## 当前代码 vs 官方文档

代码文件: `shokztype/core/volcengine_asr.py`

---

## 1. 接口地址

| 模式 | 文档地址 | 代码当前 | 说明 |
|---|---|---|---|
| 双向流式 | `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel` | `bigmodel` (使用中) | 每输入一包返回一包 |
| 双向流式**优化版** | `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async` | 未使用 | **文档推荐**，结果有变化才返回，RTF/首字/尾字时延更优 |
| 流式输入 | `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream` | 未使用 | 音频>15s或负包后才返回，准确率更高 |

## 2. 鉴权 Header

| 字段 | 文档 | 代码当前 |
|---|---|---|
| APP ID | `X-Api-App-Key` | `X-Api-Key` |
| Access Token | `X-Api-Access-Token` | `X-Api-Resource-Id` |
| Request ID | `X-Api-Request-Id` | `X-Api-Request-Id` |

代码中的 Header 名称与文档不完全一致，需确认是否为另一种鉴权方式。

## 3. 已使用的请求参数

```python
# _make_request_payload() 当前发送:
{
    "user": {"uid": "<uuid>"},
    "audio": {"format": "pcm", "rate": 16000, "bits": 16, "channel": 1},
    "request": {
        "model_name": "bigmodel",
        "enable_itn": True,
        "enable_punc": True,
        "show_utterances": True,
        "result_type": "full",
    },
}
```

## 4. 文档支持但未使用的参数

### 4.1 性能优化（建议开启）

| 参数 | 类型 | 默认 | 说明 | 限制 |
|---|---|---|---|---|
| `enable_nonstream` | bool | false | 二遍识别：流式快速出字 + nostream 重新识别提升准确率 | 仅 `bigmodel_async` |
| `enable_ddc` | bool | false | 语义顺滑：删除语气词、重复词、停顿词 | |
| `enable_accelerate_text` | bool | false | 首字返回加速（降低首字准确率） | |
| `accelerate_score` | int | 0 | 加速程度 [0-20]，越大越快 | 配合 enable_accelerate_text |

### 4.2 VAD/判停控制

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `end_window_size` | int(ms) | 800 | 强制判停时间，静音超过该值输出 definite。最小 200ms |
| `force_to_speech_time` | int(ms) | - | 音频超过该时长才尝试判停，推荐 1000 |
| `vad_segment_duration` | int(ms) | 3000 | 语义切句最大静音阈值。配置 end_window_size 后失效 |

### 4.3 说话人/语种/情绪

| 参数 | 类型 | 说明 | 限制 |
|---|---|---|---|
| `enable_speaker_info` | bool | 说话人聚类分离 | 需 `ssd_version="200"` + `enable_nonstream=true`（仅 bigmodel_async） |
| `ssd_version` | string | SSD 版本号，"200" 为大模型 SSD | |
| `enable_lid` | bool | 语种检测，additions 中返回 lid_lang | 仅 nostream / bigmodel_async |
| `enable_emotion_detection` | bool | 情绪检测 (angry/happy/neutral/sad/surprise) | 仅 nostream / bigmodel_async |
| `enable_gender_detection` | bool | 性别检测 (male/female) | 仅 nostream / bigmodel_async |

### 4.4 热词/上下文

| 参数 | 层级 | 说明 |
|---|---|---|
| `corpus.context` | request.corpus | 热词直传（双向流式100tokens，nostream 5000词）或上下文（800tokens/20轮） |
| `corpus.boosting_table_name` | request.corpus | 自学习平台热词表名称 |
| `corpus.boosting_table_id` | request.corpus | 自学习平台热词表 ID |
| `corpus.correct_table_name` | request.corpus | 替换词表名称 |
| `corpus.correct_table_id` | request.corpus | 替换词表 ID |

热词直传示例:
```json
"corpus": {
    "context": "{\"hotwords\":[{\"word\":\"热词1号\"}, {\"word\":\"热词2号\"}]}"
}
```

上下文支持传入图片辅助识别:
```json
"corpus": {
    "context": "{\"context_data\":[...], \"image_url\": \"...\"}"
}
```

### 4.5 其他

| 参数 | 类型 | 说明 |
|---|---|---|
| `output_zh_variant` | string | 繁体输出: `traditional` / `tw` / `hk` |
| `sensitive_words_filter` | string | 敏感词过滤/替换 |
| `show_speech_rate` | bool | 分句携带语速 (token/s) |
| `show_volume` | bool | 分句携带音量 (dB) |
| `audio.language` | string | 指定识别语言 (仅 nostream) |
| `enable_poi_fc` | bool | POI function call (地图领域辅助) |
| `enable_music_fc` | bool | 音乐 function call (音乐领域辅助) |

## 5. 分包建议

文档要求:
- 单包音频 100~200ms
- 发包间隔 100~200ms
- **双向流式 200ms 性能最优**

代码当前: 200ms / 6400 bytes（符合要求）
## 6. 优化建议（优先级排序）

1. **切换 `bigmodel_async`** — 文档明确推荐，性能更优
2. **开启 `enable_ddc`** — 语义顺滑，对语音转文字场景非常有用
3. **开启 `enable_nonstream`** — 二遍识别（需先切 bigmodel_async），兼顾速度和准确率
4. **配置 `end_window_size`** — 可调判停灵敏度（默认 800ms）
5. **利用 `corpus.context`** — 传入热词提升专业术语识别率
6. **确认鉴权 Header** — 与文档对齐 `X-Api-App-Key` / `X-Api-Access-Token`

