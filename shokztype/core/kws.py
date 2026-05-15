"""KWS (Keyword Spotting) — sherpa-onnx 流式关键词检测封装"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class KwsResult:
    keyword: str
    timestamp: float  # 检测时刻（秒，相对于 feed 累计帧数）


def _safe_ascii_path(path: str, dest_name: str) -> str:
    """如果路径含非 ASCII 字符（如中文），自动复制到 ~/.shokztype/ 并返回 ASCII 路径。

    对 keywords.txt 每次都同步（文件小且可能变化）；
    对模型目录仅在目标不存在时复制（避免重复拷贝大文件）。
    """
    try:
        path.encode("ascii")
        return path  # 纯 ASCII，无需处理
    except UnicodeEncodeError:
        pass

    import shutil
    safe_base = os.path.expanduser("~/.shokztype")
    dest = os.path.join(safe_base, dest_name)
    os.makedirs(safe_base, exist_ok=True)

    if os.path.isdir(path):
        if not os.path.exists(dest):
            logger.info("KWS 模型路径含中文，复制到 %s", dest)
            shutil.copytree(path, dest)
    else:
        logger.debug("KWS 文件路径含中文，同步到 %s", dest)
        shutil.copy2(path, dest)

    return dest


class KwsDetector:
    """流式关键词检测器，封装 sherpa-onnx KeywordSpotter。"""

    def __init__(self, config: Dict[str, Any]) -> None:
        import sherpa_onnx

        from shokztype import APP_DIR

        kws_cfg = config.get("kws", {})
        model_dir = kws_cfg.get("model_dir", "")
        keywords_file = kws_cfg.get("keywords_file", "keywords.txt")

        if model_dir and not os.path.isabs(model_dir):
            model_dir = os.path.join(APP_DIR, model_dir)
        if keywords_file and not os.path.isabs(keywords_file):
            keywords_file = os.path.join(APP_DIR, keywords_file)

        # 自动处理含中文的路径（sherpa-onnx C++ 层不支持 Unicode 路径）
        model_dir = _safe_ascii_path(model_dir, "kws-model")
        keywords_file = _safe_ascii_path(keywords_file, "keywords.txt")

        encoder = os.path.join(model_dir, "encoder-epoch-13-avg-2-chunk-16-left-64.onnx")
        decoder = os.path.join(model_dir, "decoder-epoch-13-avg-2-chunk-16-left-64.onnx")
        joiner = os.path.join(model_dir, "joiner-epoch-13-avg-2-chunk-16-left-64.onnx")
        tokens = os.path.join(model_dir, "tokens.txt")

        for f in (encoder, decoder, joiner, tokens):
            if not os.path.isfile(f):
                raise FileNotFoundError(f"KWS model file not found: {f}")
        if not os.path.isfile(keywords_file):
            raise FileNotFoundError(f"Keywords file not found: {keywords_file}")
        with open(keywords_file, "r", encoding="utf-8") as _f:
            if not _f.read().strip():
                raise ValueError(f"Keywords file is empty: {keywords_file}")

        self._kws = sherpa_onnx.KeywordSpotter(
            tokens=tokens,
            encoder=encoder,
            decoder=decoder,
            joiner=joiner,
            num_threads=2,
            keywords_file=keywords_file,
            provider="cpu",
            keywords_score=kws_cfg.get("keywords_score", 1.0),
            keywords_threshold=kws_cfg.get("score_threshold", 0.25),
            num_trailing_blanks=kws_cfg.get("num_trailing_blanks", 1),
            max_active_paths=4,
        )
        self._stream = self._kws.create_stream()
        self._sample_rate = 16000
        self._total_samples = 0
        logger.info("KWS detector initialized, keywords: %s", keywords_file)

    # 模型测试音频的典型 RMS（int16 → float32 后约 0.096）
    _TARGET_RMS = 0.096

    def feed(self, samples: np.ndarray) -> Optional[KwsResult]:
        """送入音频帧，返回检测结果或 None。

        Args:
            samples: float32 归一化音频 [-1, 1]，或 int16 原始音频。
        """
        if samples.dtype == np.int16:
            samples = (samples / 32768.0).astype(np.float32)
        elif samples.dtype != np.float32:
            samples = samples.astype(np.float32)

        # 自动增益归一化：麦克风音量差异很大，统一到模型期望的 RMS 水平
        rms = float(np.sqrt(np.mean(samples ** 2)))
        if self._total_samples % (self._sample_rate * 2) < len(samples):
            logger.debug("KWS feed RMS=%.4f samples=%d", rms, len(samples))
        if rms > 1e-6:
            gain = self._TARGET_RMS / rms
            # 限制增益倍数，避免静音时噪声爆炸
            gain = min(gain, 50.0)
            samples = samples * gain

        self._stream.accept_waveform(self._sample_rate, samples)
        self._total_samples += len(samples)

        while self._kws.is_ready(self._stream):
            self._kws.decode_stream(self._stream)
            result = self._kws.get_result(self._stream)
            if result:
                keyword = result.strip()
                timestamp = self._total_samples / self._sample_rate
                logger.info("KWS detected: '%s' at %.2fs", keyword, timestamp)
                self._kws.reset_stream(self._stream)
                return KwsResult(keyword=keyword, timestamp=timestamp)

        return None

    def reset(self) -> None:
        """重置流状态。"""
        self._stream = self._kws.create_stream()
        self._total_samples = 0

    def cleanup(self) -> None:
        """释放资源。"""
        self._stream = None
        self._kws = None
