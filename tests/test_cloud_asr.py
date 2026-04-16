"""Tests for CloudASR DashScope wrapper."""

import os
import sys
import types
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


def _setup_dashscope_mocks():
    """创建 dashscope 模块的 mock 结构，供延迟导入使用。"""
    mock_dashscope = types.ModuleType("dashscope")
    mock_audio = types.ModuleType("dashscope.audio")
    mock_asr = types.ModuleType("dashscope.audio.asr")

    MockRecognition = MagicMock()
    mock_asr.Recognition = MockRecognition
    mock_asr.RecognitionCallback = type("RecognitionCallback", (), {
        "on_open": lambda self: None,
        "on_complete": lambda self: None,
        "on_error": lambda self, result: None,
        "on_close": lambda self: None,
        "on_event": lambda self, result: None,
    })
    mock_asr.RecognitionResult = MagicMock()
    mock_asr.RecognitionResult.is_sentence_end = staticmethod(lambda s: True)

    mock_audio.asr = mock_asr
    mock_dashscope.audio = mock_audio
    mock_dashscope.api_key = None

    modules = {
        "dashscope": mock_dashscope,
        "dashscope.audio": mock_audio,
        "dashscope.audio.asr": mock_asr,
    }
    return modules, MockRecognition


class TestTranscribeFile:
    def test_result_format_on_success(self, tmp_path):
        """验证成功时返回字典包含所有必要字段。"""
        from http import HTTPStatus

        cfg = _base_config(api_key="sk-test")
        asr = CloudASR(cfg)

        fake_sentence = {"text": "你好世界", "end_time": 1000}
        modules, MockRecognition = _setup_dashscope_mocks()
        instance = MockRecognition.return_value

        # transcribe_file() 使用同步 call()，直接返回 RecognitionResult
        mock_result = MagicMock()
        mock_result.status_code = HTTPStatus.OK
        mock_result.get_sentence.return_value = [fake_sentence]
        instance.call.return_value = mock_result

        wav_file = tmp_path / "test.wav"
        wav_file.write_bytes(b"\x00" * 100)

        with patch.dict(sys.modules, modules):
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

        modules, MockRecognition = _setup_dashscope_mocks()
        instance = MockRecognition.return_value
        instance.call.side_effect = ConnectionError("网络不可达")

        wav_file = tmp_path / "test.wav"
        wav_file.write_bytes(b"\x00" * 100)

        with patch.dict(sys.modules, modules):
            result = asr.transcribe_file(str(wav_file))

        assert result["success"] is False
        assert "网络不可达" in result["error"]
