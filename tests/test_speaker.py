"""Tests for SpeakerProcessor voiceprint gate features."""

import logging
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from shokztype.core.speaker import SpeakerProcessor, SpeakerResult


class FakeSpeakerProcessor:
    """Minimal stand-in that avoids loading the real CAM++ model."""

    def __init__(self, config):
        from shokztype.core.speaker_db import SpeakerDB
        spk_cfg = config.get("speaker", {})
        self._threshold = spk_cfg.get("threshold", 0.45)
        self._whitelist = set(spk_cfg.get("whitelist", []))
        self._incremental_learn = spk_cfg.get("incremental_learn", True)
        self._incremental_margin = spk_cfg.get("incremental_margin", 0.10)
        self._max_embeddings = spk_cfg.get("max_embeddings", 50)
        self._db = SpeakerDB(spk_cfg.get("db_path", "test_speaker_db.json"))
        # Attach the same methods we want to test
        self.should_transcribe = SpeakerProcessor.should_transcribe.__get__(self)

    def extract_embedding(self, audio):
        """Return a deterministic fake embedding based on audio content."""
        rng = np.random.RandomState(42)
        return rng.randn(192).astype(np.float32)

    @property
    def db(self):
        return self._db


def _make_config(tmp_path, **overrides):
    cfg = {
        "speaker": {
            "enabled": True,
            "mode": "filter",
            "threshold": 0.45,
            "db_path": str(tmp_path / "test_spk.json"),
            "whitelist": ["alice"],
            "incremental_learn": True,
            "incremental_margin": 0.10,
            "max_embeddings": 50,
        }
    }
    cfg["speaker"].update(overrides)
    return cfg


@pytest.fixture
def proc(tmp_path):
    cfg = _make_config(tmp_path)
    return FakeSpeakerProcessor(cfg)


def test_should_transcribe_rejects_non_whitelist(proc, caplog):
    """Non-whitelist speaker should be rejected with INFO log."""
    audio = np.random.randint(-32768, 32767, size=16000, dtype=np.int16)
    with caplog.at_level(logging.INFO):
        ok, sid = proc.should_transcribe(audio)
    assert ok is False
    assert any("reject" in r.message.lower() for r in caplog.records)


def test_incremental_learn_updates_centroid(tmp_path):
    """When score > threshold + margin, centroid should be updated."""
    cfg = _make_config(tmp_path)
    proc = FakeSpeakerProcessor(cfg)

    emb = np.random.RandomState(42).randn(192).astype(np.float32)
    proc.db.enroll("alice", emb)
    old_count = proc.db._speakers["alice"]["sample_count"]

    audio = np.random.randint(-32768, 32767, size=16000, dtype=np.int16)
    ok, sid = proc.should_transcribe(audio)

    assert ok is True
    assert sid == "alice"
    assert proc.db._speakers["alice"]["sample_count"] == old_count + 1


def test_incremental_learn_disabled(tmp_path):
    """When incremental_learn=False, centroid should not be updated."""
    cfg = _make_config(tmp_path, incremental_learn=False)
    proc = FakeSpeakerProcessor(cfg)

    emb = np.random.RandomState(42).randn(192).astype(np.float32)
    proc.db.enroll("alice", emb)
    old_count = proc.db._speakers["alice"]["sample_count"]

    audio = np.random.randint(-32768, 32767, size=16000, dtype=np.int16)
    ok, sid = proc.should_transcribe(audio)

    assert ok is True
    assert proc.db._speakers["alice"]["sample_count"] == old_count
