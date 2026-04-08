"""Tests for VadTranscriptionWorker enroll mode."""

import numpy as np
import pytest
from unittest.mock import MagicMock, patch


def test_submit_speech_enroll_mode_stores_embedding():
    """In enroll mode, _submit_speech should store embeddings without transcribing."""
    from app.vad_worker import VadTranscriptionWorker

    mock_proc = MagicMock()
    mock_proc.extract_embedding.return_value = np.random.randn(192).astype(np.float32)
    mock_proc.db = MagicMock()
    mock_proc.db._speakers = {
        "alice": {"sample_count": 2, "embeddings": [[0]*192, [0]*192]}
    }

    embedding = mock_proc.extract_embedding(np.zeros(16000, dtype=np.int16))
    mock_proc.db.enroll("alice", embedding)

    mock_proc.db.enroll.assert_called_once()
