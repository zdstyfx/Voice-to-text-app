"""Tests for VadTranscriptionWorker diarize mode."""

import queue

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from app.speaker_cluster import SpeakerCluster


def test_submit_speech_diarize_assigns_speaker():
    """In diarize mode, _submit_speech should call SpeakerCluster.assign and queue with speaker_id."""
    from app.vad_worker import VadTranscriptionWorker

    mock_proc = MagicMock()
    emb = np.random.randn(192).astype(np.float32)
    mock_proc.extract_embedding.return_value = emb

    cluster = SpeakerCluster(threshold=0.45)

    with patch.object(VadTranscriptionWorker, '__init__', lambda self, **kw: None):
        worker = VadTranscriptionWorker()
        worker._speaker_processor = mock_proc
        worker._speaker_mode = "diarize"
        worker._speaker_cluster = cluster
        worker._speech_buffer = [np.zeros(16000, dtype=np.int16)]
        worker._audio_cfg = {"sample_rate": 16000}
        worker._transcription_task_count = 0
        worker._transcription_queue = queue.Queue(maxsize=10)

        worker._submit_speech()

        mock_proc.extract_embedding.assert_called_once()
        assert worker._transcription_queue.qsize() == 1
        item = worker._transcription_queue.get_nowait()
        samples, speaker_id, speaker_confidence = item
        assert speaker_id == "说话人1"


def test_submit_speech_diarize_embedding_failure_sets_none():
    """If embedding extraction fails in diarize mode, speaker should be None."""
    from app.vad_worker import VadTranscriptionWorker

    mock_proc = MagicMock()
    mock_proc.extract_embedding.side_effect = RuntimeError("too short")

    cluster = SpeakerCluster(threshold=0.45)

    with patch.object(VadTranscriptionWorker, '__init__', lambda self, **kw: None):
        worker = VadTranscriptionWorker()
        worker._speaker_processor = mock_proc
        worker._speaker_mode = "diarize"
        worker._speaker_cluster = cluster
        worker._speech_buffer = [np.zeros(16000, dtype=np.int16)]
        worker._audio_cfg = {"sample_rate": 16000}
        worker._transcription_task_count = 0
        worker._transcription_queue = queue.Queue(maxsize=10)

        worker._submit_speech()

        assert worker._transcription_queue.qsize() == 1
        item = worker._transcription_queue.get_nowait()
        _, speaker_id, speaker_confidence = item
        assert speaker_id is None
        assert speaker_confidence is None
