"""Tests for KwsDetector."""
import numpy as np
import pytest


def test_kws_detector_init_and_silence():
    """KwsDetector 初始化并 feed 静音帧不触发检测"""
    from app.kws import KwsDetector

    config = {
        "kws": {
            "model_dir": "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20",
            "keywords_file": "keywords.txt",
            "score_threshold": 0.25,
        }
    }
    detector = KwsDetector(config)
    # Feed 1 second of silence
    silence = np.zeros(16000, dtype=np.float32)
    result = detector.feed(silence)
    assert result is None
    detector.cleanup()


def test_kws_detector_accepts_int16():
    """KwsDetector 能接受 int16 格式音频"""
    from app.kws import KwsDetector

    config = {
        "kws": {
            "model_dir": "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20",
            "keywords_file": "keywords.txt",
            "score_threshold": 0.25,
        }
    }
    detector = KwsDetector(config)
    silence = np.zeros(1600, dtype=np.int16)
    result = detector.feed(silence)
    assert result is None
    detector.cleanup()


def test_kws_detector_reset():
    """reset 后 detector 仍可正常工作"""
    from app.kws import KwsDetector

    config = {
        "kws": {
            "model_dir": "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20",
            "keywords_file": "keywords.txt",
            "score_threshold": 0.25,
        }
    }
    detector = KwsDetector(config)
    detector.reset()
    silence = np.zeros(1600, dtype=np.float32)
    result = detector.feed(silence)
    assert result is None
    detector.cleanup()
