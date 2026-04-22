"""Tests for VolcEngineASR — 火山引擎 Seed ASR 流式语音识别。"""

import gzip
import json
import struct
import sys
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from shokztype.core.volcengine_asr import (
    VolcEngineASR,
    _build_header,
    _build_full_client_request,
    _build_audio_frame,
    _parse_response,
    _MSG_FULL_CLIENT_REQUEST,
    _MSG_AUDIO_ONLY,
    _MSG_FULL_SERVER_RESPONSE,
    _MSG_ERROR,
    _FLAG_NONE,
    _FLAG_LAST_PACKET,
    _SERIAL_JSON,
    _SERIAL_NONE,
    _COMPRESS_NONE,
    _COMPRESS_GZIP,
)
from shokztype.core.cloud_asr_factory import create_cloud_asr


def _base_config(**volc_overrides):
    volc = {
        "api_key": "",
        "model_id": "",
        "ws_url": "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
    }
    volc.update(volc_overrides)
    return {
        "asr": {"backend": "volcengine", "volcengine": volc},
        "cloud_asr": {
            "provider": "volcengine",
            "format": "pcm",
            "sample_rate": 16000,
        },
    }


# ---------------------------------------------------------------------------
# 凭证解析
# ---------------------------------------------------------------------------

class TestVolcEngineASRInit:
    def test_credentials_from_config(self):
        cfg = _base_config(api_key="test-key-123")
        asr = VolcEngineASR(cfg)
        assert asr._api_key == "test-key-123"

    def test_missing_api_key_raises(self):
        cfg = _base_config(api_key="")
        with pytest.raises(ValueError, match="API Key"):
            VolcEngineASR(cfg)

    def test_ws_url_default(self):
        cfg = _base_config(api_key="test-key")
        del cfg["asr"]["volcengine"]["ws_url"]
        asr = VolcEngineASR(cfg)
        assert "openspeech.bytedance.com" in asr._ws_url

    def test_model_id_stored(self):
        cfg = _base_config(api_key="test-key", model_id="my-model-123")
        asr = VolcEngineASR(cfg)
        assert asr._model_id == "my-model-123"


# ---------------------------------------------------------------------------
# 二进制协议
# ---------------------------------------------------------------------------

class TestBinaryProtocol:
    def test_build_header_full_client_request(self):
        h = _build_header(_MSG_FULL_CLIENT_REQUEST, _FLAG_NONE, _SERIAL_JSON, _COMPRESS_NONE)
        assert len(h) == 4
        assert h[0] == 0x11  # version=1, header_size=1
        assert h[1] == 0x10  # msg_type=1(full client req), flags=0
        assert h[2] == 0x10  # serial=JSON, compress=none
        assert h[3] == 0x00

    def test_build_header_audio(self):
        h = _build_header(_MSG_AUDIO_ONLY, _FLAG_NONE, _SERIAL_NONE, _COMPRESS_NONE)
        assert h[1] == 0x20  # msg_type=2(audio), flags=0

    def test_build_header_audio_last(self):
        h = _build_header(_MSG_AUDIO_ONLY, _FLAG_LAST_PACKET, _SERIAL_NONE, _COMPRESS_NONE)
        assert h[1] == 0x22  # msg_type=2(audio), flags=2(last)

    def test_build_full_client_request(self):
        payload = {"audio": {"format": "pcm"}}
        frame = _build_full_client_request(payload, sequence=1)
        assert frame[0] == 0x11
        assert frame[1] == 0x11  # FULL_CLIENT_REQUEST + POS_SEQUENCE
        assert frame[2] == 0x11  # JSON + GZIP
        # header(4) + sequence(4) + size(4) + gzip payload
        seq = struct.unpack(">i", frame[4:8])[0]
        assert seq == 1
        size = struct.unpack(">I", frame[8:12])[0]
        decoded = json.loads(gzip.decompress(frame[12:12 + size]))
        assert decoded == payload

    def test_build_audio_frame(self):
        pcm = b"\x00\x01" * 100
        frame = _build_audio_frame(pcm, is_last=False)
        assert frame[1] == 0x20  # audio, not last
        size = struct.unpack(">I", frame[4:8])[0]
        decompressed = gzip.decompress(frame[8:8 + size])
        assert decompressed == pcm

    def test_build_audio_frame_last(self):
        frame = _build_audio_frame(b"", is_last=True)
        assert frame[1] == 0x22  # audio, last (negative packet)

    def test_parse_server_response(self):
        payload = {"result": {"text": "你好世界"}}
        payload_bytes = gzip.compress(json.dumps(payload).encode("utf-8"))
        header = _build_header(_MSG_FULL_SERVER_RESPONSE, 0x1, _SERIAL_JSON, _COMPRESS_GZIP)
        data = (
            header
            + struct.pack(">i", 1)
            + struct.pack(">I", len(payload_bytes))
            + payload_bytes
        )
        result = _parse_response(data)
        assert result["result"]["text"] == "你好世界"
        assert result["_sequence"] == 1

    def test_parse_server_response_no_compression(self):
        payload = {"result": {"text": "无压缩"}}
        payload_bytes = json.dumps(payload).encode("utf-8")
        header = _build_header(_MSG_FULL_SERVER_RESPONSE, 0x1, _SERIAL_JSON, _COMPRESS_NONE)
        data = (
            header
            + struct.pack(">i", 2)
            + struct.pack(">I", len(payload_bytes))
            + payload_bytes
        )
        result = _parse_response(data)
        assert result["result"]["text"] == "无压缩"

    def test_parse_error_response(self):
        error_msg = "invalid format"
        error_bytes = error_msg.encode("utf-8")
        header = _build_header(_MSG_ERROR, _FLAG_NONE, _SERIAL_NONE, _COMPRESS_NONE)
        data = (
            header
            + struct.pack(">I", 4001)
            + struct.pack(">I", len(error_bytes))
            + error_bytes
        )
        result = _parse_response(data)
        assert result["error"] is True
        assert result["code"] == 4001
        assert "invalid format" in result["message"]

    def test_parse_too_short_raises(self):
        with pytest.raises(ValueError, match="过短"):
            _parse_response(b"\x11\x90")


# ---------------------------------------------------------------------------
# transcribe_file 返回格式
# ---------------------------------------------------------------------------

class TestTranscribeFile:
    def test_result_format_on_success(self, tmp_path):
        import wave

        cfg = _base_config(api_key="test-key")
        asr = VolcEngineASR(cfg)

        # 创建测试 WAV 文件
        wav_file = tmp_path / "test.wav"
        with wave.open(str(wav_file), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 1600)  # 100ms

        # 构造模拟服务端响应
        def make_resp(text, definite=True):
            payload = {
                "result": {
                    "text": text,
                    "utterances": [{"text": text, "definite": definite, "start_time": 0, "end_time": 100}],
                },
            }
            payload_bytes = json.dumps(payload).encode("utf-8")
            header = _build_header(_MSG_FULL_SERVER_RESPONSE, 0x1, _SERIAL_JSON, _COMPRESS_NONE)
            return (
                header
                + struct.pack(">i", 1)
                + struct.pack(">I", len(payload_bytes))
                + payload_bytes
            )

        # Mock websockets
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            make_resp("", definite=False),  # 第一个响应（确认连接）
            make_resp("你好世界", definite=True),  # 音频响应
        ])
        mock_ws.send = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        mock_connect = MagicMock(return_value=mock_ws)

        with patch.dict(sys.modules, {"websockets": MagicMock(connect=mock_connect)}):
            with patch.object(asr, "_transcribe_file_async") as mock_async:
                # 直接模拟异步方法的返回值
                mock_async.return_value = {
                    "result": {
                        "text": "你好世界",
                        "utterances": [{"text": "你好世界", "definite": True}],
                    }
                }
                result = asr.transcribe_file(str(wav_file))

        assert result["success"] is True
        assert result["text"] == "你好世界"
        assert "raw_text" in result
        assert "confidence" in result
        assert "duration" in result

    def test_result_format_on_error(self, tmp_path):
        import wave

        cfg = _base_config(api_key="test-key")
        asr = VolcEngineASR(cfg)

        wav_file = tmp_path / "test.wav"
        with wave.open(str(wav_file), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 1600)

        with patch.object(asr, "_transcribe_file_async", side_effect=ConnectionError("网络不可达")):
            result = asr.transcribe_file(str(wav_file))

        assert result["success"] is False
        assert "网络不可达" in result["error"]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class TestCloudASRFactory:
    def test_factory_returns_volcengine(self):
        cfg = _base_config(api_key="key123")
        asr = create_cloud_asr(cfg)
        assert isinstance(asr, VolcEngineASR)

    def test_factory_returns_dashscope_by_default(self):
        cfg = {
            "cloud_asr": {
                "provider": "dashscope",
                "api_key": "sk-test",
            },
        }
        from shokztype.core.cloud_asr import CloudASR
        asr = create_cloud_asr(cfg)
        assert isinstance(asr, CloudASR)
