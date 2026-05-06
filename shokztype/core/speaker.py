"""Speaker recognition processor — CAM++ embedding extraction and matching."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import torch

from .speaker_db import SpeakerDB

logger = logging.getLogger(__name__)


@dataclass
class SpeakerResult:
    speaker_id: str        # "张三" | "speaker_001" | "unknown"
    confidence: float      # 余弦相似度 0~1
    is_known: bool         # 是否匹配到已注册说话人


class SpeakerProcessor:
    """Loads CAM++ model and provides speaker identification / filtering."""

    def __init__(self, config: Dict[str, Any]) -> None:
        spk_cfg = config.get("speaker", {})
        model_id = spk_cfg.get("model", "iic/speech_campplus_sv_zh-cn_16k-common")
        self._threshold = spk_cfg.get("threshold", 0.65)
        self._auto_learn = spk_cfg.get("auto_learn", False)
        self._whitelist = set(spk_cfg.get("whitelist", []))
        self._incremental_learn = spk_cfg.get("incremental_learn", True)
        self._incremental_margin = spk_cfg.get("incremental_margin", 0.10)
        self._max_embeddings = spk_cfg.get("max_embeddings", 50)
        db_path = spk_cfg.get("db_path", "speaker_db.json")
        if not os.path.isabs(db_path):
            from shokztype import DATA_DIR
            db_path = os.path.join(DATA_DIR, db_path)

        # Load speaker database
        self._db = SpeakerDB(db_path)

        # Load CAM++ model: 优先从 models/ 目录加载，再走 modelscope 缓存
        logger.info("Loading CAM++ speaker model: %s", model_id)

        model_dir = None
        short_name = model_id.split('/')[-1] if '/' in model_id else model_id

        # 1. 检查程序目录下的 models/
        from shokztype import APP_DIR
        bundled = os.path.join(APP_DIR, "models", short_name)
        if os.path.isdir(bundled):
            model_dir = bundled
            logger.info("Using bundled speaker model: %s", bundled)

        # 2. 走 modelscope 缓存
        if model_dir is None:
            from shokztype.core.download_models import get_model_cache_path
            model_dir = get_model_cache_path(model_id, None)

        config_path = os.path.join(model_dir, "configuration.json")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        model_config = cfg["model"]["model_config"]
        pretrained_model = cfg["model"]["pretrained_model"]

        # 使用自己的 CAM++ 实现（纯 PyTorch，不依赖 modelscope）
        from shokztype.core.campplus import SpeakerVerificationCAMPPlus

        self._model = SpeakerVerificationCAMPPlus(
            model_dir=model_dir,
            model_config=model_config,
            device="cpu",
            pretrained_model=pretrained_model,
        )
        self._model.embedding_model.eval()
        logger.info("CAM++ speaker model loaded from: %s", model_dir)

    @property
    def db(self) -> SpeakerDB:
        return self._db

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def extract_embedding(self, audio: np.ndarray) -> np.ndarray:
        """Extract 192-dim speaker embedding from 16kHz int16 audio.

        Args:
            audio: 1-D int16 numpy array at 16kHz.

        Returns:
            192-dim float32 embedding vector.
        """
        if audio.dtype == np.int16:
            audio_f32 = (audio / 32768.0).astype(np.float32)
        else:
            audio_f32 = audio.astype(np.float32)

        # Normalize volume to prevent low-volume mic from degrading embeddings
        peak = np.max(np.abs(audio_f32))
        if peak > 1e-6:
            audio_f32 = audio_f32 / peak * 0.95

        with torch.no_grad():
            embedding = self._model(audio_f32)  # [1, 192]
        return embedding.squeeze(0).numpy().astype(np.float32)

    def identify(self, audio: np.ndarray) -> SpeakerResult:
        """Identification mode: return best matching speaker + confidence.

        Workflow:
        1. Extract embedding
        2. Match against DB
        3. >= threshold → known speaker
        4. < threshold + auto_learn → create new auto speaker
        5. < threshold → unknown
        """
        try:
            embedding = self.extract_embedding(audio)
        except Exception as exc:
            logger.warning("Embedding extraction failed: %s", exc)
            return SpeakerResult(speaker_id="unknown", confidence=0.0, is_known=False)

        name, score = self._db.match(embedding, self._threshold)

        if name is not None:
            logger.info("Speaker match: '%s' score=%.4f (threshold=%.2f)", name, score, self._threshold)
            return SpeakerResult(speaker_id=name, confidence=score, is_known=True)

        # Log best score even when below threshold for debugging
        logger.info("Speaker no match: best_score=%.4f (threshold=%.2f)", score, self._threshold)

        if self._auto_learn:
            auto_name = self._db.add_auto_speaker(embedding)
            return SpeakerResult(speaker_id=auto_name, confidence=score, is_known=False)

        return SpeakerResult(speaker_id="unknown", confidence=score, is_known=False)

    def should_transcribe(self, audio: np.ndarray) -> tuple[bool, str]:
        """Filter mode: check if speaker is in whitelist.

        Features:
        - Rejection logging with top-2 match info
        - Incremental learning when confidence exceeds threshold + margin

        Returns:
            (should_transcribe, speaker_id)
        """
        try:
            embedding = self.extract_embedding(audio)
        except Exception as exc:
            logger.warning("Embedding extraction failed: %s", exc)
            return False, "unknown"

        top2 = self._db.match_top2(embedding)
        duration_s = len(audio) / 16000.0

        if not top2:
            logger.info(
                "Speaker gate rejected: no enrolled speakers (duration=%.1fs)",
                duration_s,
            )
            return False, "unknown"

        best_name, best_score = top2[0]
        second_info = ""
        if len(top2) > 1:
            second_info = f", second={top2[1][0]} score={top2[1][1]:.4f}"

        if not self._whitelist:
            return True, best_name

        if best_name in self._whitelist and best_score >= self._threshold:
            # Incremental learning
            if (
                self._incremental_learn
                and best_score >= self._threshold + self._incremental_margin
            ):
                self._db.update_centroid(
                    best_name, embedding, self._max_embeddings
                )
                logger.debug(
                    "Incremental learn: %s score=%.4f", best_name, best_score
                )
            return True, best_name

        # Rejected
        logger.info(
            "Speaker gate rejected: best=%s score=%.4f (threshold=%.2f)%s duration=%.1fs",
            best_name,
            best_score,
            self._threshold,
            second_info,
            duration_s,
        )
        return False, best_name
