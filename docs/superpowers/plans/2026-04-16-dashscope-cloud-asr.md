# DashScope 云端 ASR 集成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 集成 DashScope Paraformer 云端 ASR，通过配置切换本地/云端后端。

**Architecture:** 新建 `app/cloud_asr.py` 封装 DashScope Recognition SDK，返回与 `FunASRServer.transcribe_audio()` 相同格式的字典。`app/transcribe.py` 和 `app/vad_worker.py` 根据 `asr.backend` 配置选择初始化本地或云端引擎，调用点通过统一返回格式无缝切换。

**Tech Stack:** dashscope SDK (1.25.17), DashScope Recognition API (paraformer-realtime-v2)

---

## 文件结构

| 文件 | 职责 | 操作 |
|------|------|------|
| `app/cloud_asr.py` | CloudASR 封装类：API key 解析、DashScope Recognition 调用、结果格式转换 | 新建 |
| `tests/test_cloud_asr.py` | CloudASR 单元测试：初始化、API key 解析、transcribe_file 结果格式 | 新建 |
| `app/config.py` | 新增 `asr.backend` 和 `cloud_asr` 配置段 | 修改 |
| `app/transcribe.py` | F2 模式条件初始化 + `_transcribe_once` 路由 | 修改 |
| `app/vad_worker.py` | VAD 模式条件初始化 + `_transcribe_once` 路由 | 修改 |

---

### Task 1: 新增配置项

**Files:**
- Modify: `app/config.py:39-45`

- [ ] **Step 1: 在 `DEFAULT_CONFIG["asr"]` 中新增 `backend` 字段**

在 `app/config.py` 第 39-45 行，`"asr"` 字典中追加 `"backend"` 字段：

```python
"asr": {
    "backend": "local",  # "local" | "cloud"
    "use_vad": False,
    "use_punc": True,
    "language": "zh",
    "hotword": "",
    "batch_size_s": 60.0,
},
```

- [ ] **Step 2: 在 `DEFAULT_CONFIG` 中新增 `cloud_asr` 配置段**

在 `app/config.py` 的 `"asr"` 段之后（第 46 行附近），新增 `"cloud_asr"` 段：

```python
"cloud_asr": {
    "provider": "dashscope",
    "api_key": "",
    "model": "paraformer-realtime-v2",
    "format": "pcm",
    "sample_rate": 16000,
    "disfluency_removal": False,
},
```

- [ ] **Step 3: 验证配置加载**

Run: `python -c "from app.config import load_config; c = load_config(); print(c['asr']['backend']); print(c['cloud_asr']['provider'])"`

Expected:
```
local
dashscope
```

- [ ] **Step 4: Commit**

```bash
git add app/config.py
git commit -m "feat: add asr.backend and cloud_asr config section"
```

---

### Task 2: 实现 CloudASR 封装类

**Files:**
- Create: `app/cloud_asr.py`
- Create: `tests/test_cloud_asr.py`

- [ ] **Step 1: 编写 CloudASR 初始化和 API key 解析的测试**

创建 `tests/test_cloud_asr.py`：

```python
"""Tests for CloudASR DashScope wrapper."""

import os
import pytest
from unittest.mock import patch, MagicMock

from app.cloud_asr import CloudASR


def _base_config(**overrides):
    cfg = {
        "cloud_asr": {
            "provider": "dashscope",
            "api_key": "",
            "model": "paraformer-realtime-v2",
            "format": "pcm",
            "sample_rate": 16000,
            "disfluency_removal": False,
        },
    }
    cfg["cloud_asr"].update(overrides)
    return cfg


class TestCloudASRInit:
    def test_api_key_from_config(self):
        cfg = _base_config(api_key="sk-test123")
        asr = CloudASR(cfg)
        assert asr._api_key == "sk-test123"

    def test_api_key_from_env(self):
        cfg = _base_config(api_key="")
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "sk-env456"}):
            asr = CloudASR(cfg)
            assert asr._api_key == "sk-env456"

    def test_api_key_missing_raises(self):
        cfg = _base_config(api_key="")
        with patch.dict(os.environ, {}, clear=True):
            # 确保环境变量中也没有
            os.environ.pop("DASHSCOPE_API_KEY", None)
            with pytest.raises(ValueError, match="API key"):
                CloudASR(cfg)

    def test_config_fields_stored(self):
        cfg = _base_config(
            api_key="sk-test",
            model="paraformer-realtime-v2",
            sample_rate=16000,
        )
        asr = CloudASR(cfg)
        assert asr._model == "paraformer-realtime-v2"
        assert asr._sample_rate == 16000
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_cloud_asr.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.cloud_asr'`

- [ ] **Step 3: 实现 CloudASR 类**

创建 `app/cloud_asr.py`：

```python
"""CloudASR — DashScope Paraformer 云端语音识别封装。"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CloudASR:
    """封装 DashScope Recognition SDK，提供与 FunASRServer.transcribe_audio()
    相同返回格式的云端语音识别接口。"""

    def __init__(self, config: Dict[str, Any]) -> None:
        cloud_cfg = config.get("cloud_asr", {})
        self._api_key = self._resolve_api_key(cloud_cfg)
        self._model = cloud_cfg.get("model", "paraformer-realtime-v2")
        self._format = cloud_cfg.get("format", "pcm")
        self._sample_rate = cloud_cfg.get("sample_rate", 16000)
        self._disfluency_removal = cloud_cfg.get("disfluency_removal", False)
        logger.info("CloudASR 初始化完成，模型: %s", self._model)

    @staticmethod
    def _resolve_api_key(cloud_cfg: Dict[str, Any]) -> str:
        key = cloud_cfg.get("api_key", "")
        if key:
            return key
        key = os.environ.get("DASHSCOPE_API_KEY", "")
        if key:
            return key
        raise ValueError(
            "DashScope API key 未配置。"
            "请在 config.json 的 cloud_asr.api_key 中设置，"
            "或设置环境变量 DASHSCOPE_API_KEY。"
        )

    def transcribe_file(self, wav_path: str) -> Dict[str, Any]:
        """同步识别音频文件，返回与 FunASRServer.transcribe_audio() 相同格式的字典。

        返回:
            {"success": bool, "text": str, "raw_text": str,
             "confidence": float, "duration": float, "error": str|None}
        """
        import dashscope
        from dashscope.audio.asr import (
            Recognition,
            RecognitionCallback,
            RecognitionResult,
        )

        dashscope.api_key = self._api_key

        sentences: List[str] = []
        error_msg: Optional[str] = None
        completed = threading.Event()

        class _Callback(RecognitionCallback):
            def on_event(self, result: RecognitionResult) -> None:
                sentence = result.get_sentence()
                if sentence and RecognitionResult.is_sentence_end(sentence):
                    text = sentence.get("text", "")
                    if text:
                        sentences.append(text)

            def on_complete(self) -> None:
                completed.set()

            def on_error(self, result: RecognitionResult) -> None:
                nonlocal error_msg
                error_msg = str(result)
                completed.set()

        callback = _Callback()
        recognition = Recognition(
            model=self._model,
            callback=callback,
            format="wav",
            sample_rate=self._sample_rate,
        )

        start = time.time()
        try:
            recognition.call(
                file=wav_path,
                disfluency_removal_enabled=self._disfluency_removal,
            )
            # call() 是同步的，完成后 on_complete 已被调用
            # 但保险起见等一下 completed 事件
            completed.wait(timeout=60)
        except Exception as e:
            logger.error("DashScope ASR 调用失败: %s", e)
            return {"success": False, "error": str(e)}
        finally:
            duration = time.time() - start

        if error_msg:
            return {"success": False, "error": error_msg}

        full_text = "".join(sentences)
        return {
            "success": True,
            "text": full_text,
            "raw_text": full_text,
            "confidence": 0.95,
            "duration": duration,
        }
```

- [ ] **Step 4: 运行初始化相关测试**

Run: `python -m pytest tests/test_cloud_asr.py::TestCloudASRInit -v`

Expected: 4 tests PASS

- [ ] **Step 5: 编写 transcribe_file 返回格式的测试**

在 `tests/test_cloud_asr.py` 中追加：

```python
class TestTranscribeFile:
    def test_result_format_on_success(self, tmp_path):
        """验证成功时返回字典包含所有必要字段。"""
        cfg = _base_config(api_key="sk-test")
        asr = CloudASR(cfg)

        # Mock DashScope Recognition.call
        fake_sentence = {"text": "你好世界", "end_time": 1000}

        with patch("app.cloud_asr.Recognition") as MockRecognition:
            instance = MockRecognition.return_value

            def fake_call(file, **kwargs):
                # 模拟 on_event 回调
                callback = MockRecognition.call_args[1]["callback"]
                mock_result = MagicMock()
                mock_result.get_sentence.return_value = fake_sentence
                callback.on_event(mock_result)
                callback.on_complete()

            instance.call.side_effect = fake_call

            # 创建一个假 wav 文件
            wav_file = tmp_path / "test.wav"
            wav_file.write_bytes(b"\x00" * 100)

            result = asr.transcribe_file(str(wav_file))

        assert result["success"] is True
        assert result["text"] == "你好世界"
        assert "raw_text" in result
        assert "confidence" in result
        assert "duration" in result

    def test_result_format_on_error(self, tmp_path):
        """验证失败时返回 success=False 和 error 信息。"""
        cfg = _base_config(api_key="sk-test")
        asr = CloudASR(cfg)

        with patch("app.cloud_asr.Recognition") as MockRecognition:
            instance = MockRecognition.return_value
            instance.call.side_effect = ConnectionError("网络不可达")

            wav_file = tmp_path / "test.wav"
            wav_file.write_bytes(b"\x00" * 100)

            result = asr.transcribe_file(str(wav_file))

        assert result["success"] is False
        assert "网络不可达" in result["error"]
```

- [ ] **Step 6: 运行全部 CloudASR 测试**

Run: `python -m pytest tests/test_cloud_asr.py -v`

Expected: 6 tests PASS

- [ ] **Step 7: Commit**

```bash
git add app/cloud_asr.py tests/test_cloud_asr.py
git commit -m "feat: add CloudASR wrapper for DashScope Paraformer cloud ASR"
```

---

### Task 3: 集成到 F2 手动录音模式

**Files:**
- Modify: `app/transcribe.py:21,65-68,379-386`

- [ ] **Step 1: 修改 `TranscriptionWorker.__init__` 条件初始化**

在 `app/transcribe.py` 中，将第 65-68 行的 FunASR 无条件初始化改为条件初始化：

原代码（第 65-68 行）：
```python
        self.fun_server = FunASRServer()
        init_result = self.fun_server.initialize()
        if not init_result.get("success"):
            raise RuntimeError(f"FunASR 初始化失败: {init_result}")
```

替换为：
```python
        self._asr_backend = self.config.get("asr", {}).get("backend", "local")
        self.fun_server = None
        self.cloud_asr = None

        if self._asr_backend == "cloud":
            from .cloud_asr import CloudASR
            self.cloud_asr = CloudASR(self.config)
        else:
            self.fun_server = FunASRServer()
            init_result = self.fun_server.initialize()
            if not init_result.get("success"):
                raise RuntimeError(f"FunASR 初始化失败: {init_result}")
```

- [ ] **Step 2: 修改 `_transcribe_once` 路由到云端**

在 `app/transcribe.py` 中，将第 379-386 行的 ASR 调用改为条件路由：

原代码（第 380-386 行）：
```python
        tmp_path = self._write_temp_wav(samples)
        start = time.time()
        try:
            asr_result = self.fun_server.transcribe_audio(
                tmp_path,
                options=self.config.get("asr"),
            )
```

替换为：
```python
        tmp_path = self._write_temp_wav(samples)
        start = time.time()
        try:
            if self._asr_backend == "cloud":
                asr_result = self.cloud_asr.transcribe_file(tmp_path)
            else:
                asr_result = self.fun_server.transcribe_audio(
                    tmp_path,
                    options=self.config.get("asr"),
                )
```

- [ ] **Step 3: 验证本地模式不受影响**

Run: `python -c "from app.config import load_config; c = load_config(); print(c['asr']['backend'])"`

Expected: `local`（默认值，不影响现有行为）

- [ ] **Step 4: Commit**

```bash
git add app/transcribe.py
git commit -m "feat: wire cloud ASR backend into F2 manual recording mode"
```

---

### Task 4: 集成到 VAD 持续监听模式

**Files:**
- Modify: `app/vad_worker.py:23,57-61,447-452`

- [ ] **Step 1: 修改 `VadTranscriptionWorker.__init__` 条件初始化**

在 `app/vad_worker.py` 中，将第 57-61 行的 FunASR 无条件初始化改为条件初始化：

原代码（第 57-61 行）：
```python
        # FunASR
        self.fun_server = FunASRServer()
        init_result = self.fun_server.initialize()
        if not init_result.get("success"):
            raise RuntimeError(f"FunASR initialization failed: {init_result}")
```

替换为：
```python
        # ASR 引擎（本地或云端）
        self._asr_backend = self.config.get("asr", {}).get("backend", "local")
        self.fun_server = None
        self.cloud_asr = None

        if self._asr_backend == "cloud":
            from .cloud_asr import CloudASR
            self.cloud_asr = CloudASR(self.config)
        else:
            self.fun_server = FunASRServer()
            init_result = self.fun_server.initialize()
            if not init_result.get("success"):
                raise RuntimeError(f"FunASR initialization failed: {init_result}")
```

- [ ] **Step 2: 修改 `_transcribe_once` 路由到云端**

在 `app/vad_worker.py` 中，将第 447-452 行的 ASR 调用改为条件路由：

原代码（第 447-452 行）：
```python
        tmp_path = self._write_temp_wav(samples)
        start = time.time()
        try:
            asr_result = self.fun_server.transcribe_audio(
                tmp_path, options=self.config.get("asr")
            )
```

替换为：
```python
        tmp_path = self._write_temp_wav(samples)
        start = time.time()
        try:
            if self._asr_backend == "cloud":
                asr_result = self.cloud_asr.transcribe_file(tmp_path)
            else:
                asr_result = self.fun_server.transcribe_audio(
                    tmp_path, options=self.config.get("asr")
                )
```

- [ ] **Step 3: Commit**

```bash
git add app/vad_worker.py
git commit -m "feat: wire cloud ASR backend into VAD continuous listening mode"
```

---

### Task 5: 端到端验证

**Files:**
- 无新建/修改文件

- [ ] **Step 1: 验证本地模式仍正常工作**

Run: `python -c "from app.config import load_config; c = load_config(); assert c['asr']['backend'] == 'local'; print('OK: 默认本地模式')" `

Expected: `OK: 默认本地模式`

- [ ] **Step 2: 验证云端模式初始化（使用假 key 测试错误处理）**

Run: `python -c "from app.cloud_asr import CloudASR; asr = CloudASR({'cloud_asr': {'api_key': 'sk-test', 'model': 'paraformer-realtime-v2', 'format': 'pcm', 'sample_rate': 16000, 'disfluency_removal': False}}); print('OK: CloudASR 初始化成功')"`

Expected: `OK: CloudASR 初始化成功`

- [ ] **Step 3: 验证无 key 时的错误提示**

Run: `python -c "import os; os.environ.pop('DASHSCOPE_API_KEY', None); from app.cloud_asr import CloudASR; CloudASR({'cloud_asr': {'api_key': ''}})"`

Expected: `ValueError: DashScope API key 未配置...`

- [ ] **Step 4: 运行全部测试套件**

Run: `python -m pytest tests/test_cloud_asr.py -v`

Expected: All tests PASS

- [ ] **Step 5: Commit（如有修复）**

如果前面的验证发现问题并做了修复，提交修复：

```bash
git add -A
git commit -m "fix: address issues found during cloud ASR integration testing"
```

如无问题则跳过此步。
