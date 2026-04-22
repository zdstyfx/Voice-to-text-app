"""Tests for VadTranscriptionWorker identify mode with speaker clustering."""

import queue

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from shokztype.core.speaker_cluster import SpeakerCluster


def test_submit_speech_unknown_speaker_clusters():
    """In identify mode, unknown speakers should fall through to SpeakerCluster."""
    from shokztype.core.vad_worker import VadTranscriptionWorker

    mock_proc = MagicMock()
    emb = np.random.randn(192).astype(np.float32)
    mock_proc.extract_embedding.return_value = emb
    # identify() returns unknown speaker
    mock_result = MagicMock()
    mock_result.is_known = False
    mock_result.speaker_id = "unknown"
    mock_result.confidence = 0.2
    mock_proc.identify.return_value = mock_result

    cluster = SpeakerCluster(threshold=0.45)

    with patch.object(VadTranscriptionWorker, '__init__', lambda self, **kw: None):
        worker = VadTranscriptionWorker()
        worker._speaker_processor = mock_proc
        worker._speaker_mode = "identify"
        worker._speaker_cluster = cluster
        worker._speech_buffer = [np.zeros(16000, dtype=np.int16)]
        worker._audio_cfg = {"sample_rate": 16000}
        worker._transcription_task_count = 0
        worker._transcription_queue = queue.Queue(maxsize=10)

        worker._submit_speech()

        mock_proc.identify.assert_called_once()
        mock_proc.extract_embedding.assert_called_once()
        assert worker._transcription_queue.qsize() == 1
        item = worker._transcription_queue.get_nowait()
        samples, speaker_id, speaker_confidence = item
        assert speaker_id == "说话人1"


def test_submit_speech_known_speaker_uses_name():
    """In identify mode, known speakers should use their registered name."""
    from shokztype.core.vad_worker import VadTranscriptionWorker

    mock_proc = MagicMock()
    mock_result = MagicMock()
    mock_result.is_known = True
    mock_result.speaker_id = "张三"
    mock_result.confidence = 0.85
    mock_proc.identify.return_value = mock_result

    cluster = SpeakerCluster(threshold=0.45)

    with patch.object(VadTranscriptionWorker, '__init__', lambda self, **kw: None):
        worker = VadTranscriptionWorker()
        worker._speaker_processor = mock_proc
        worker._speaker_mode = "identify"
        worker._speaker_cluster = cluster
        worker._speech_buffer = [np.zeros(16000, dtype=np.int16)]
        worker._audio_cfg = {"sample_rate": 16000}
        worker._transcription_task_count = 0
        worker._transcription_queue = queue.Queue(maxsize=10)

        worker._submit_speech()

        mock_proc.identify.assert_called_once()
        mock_proc.extract_embedding.assert_not_called()
        assert worker._transcription_queue.qsize() == 1
        item = worker._transcription_queue.get_nowait()
        _, speaker_id, speaker_confidence = item
        assert speaker_id == "张三"
        assert speaker_confidence == 0.85


def test_submit_speech_clustering_failure_falls_back():
    """If clustering fails for unknown speaker, fall back to identify result."""
    from shokztype.core.vad_worker import VadTranscriptionWorker

    mock_proc = MagicMock()
    mock_proc.extract_embedding.side_effect = RuntimeError("too short")
    mock_result = MagicMock()
    mock_result.is_known = False
    mock_result.speaker_id = "unknown"
    mock_result.confidence = 0.15
    mock_proc.identify.return_value = mock_result

    cluster = SpeakerCluster(threshold=0.45)

    with patch.object(VadTranscriptionWorker, '__init__', lambda self, **kw: None):
        worker = VadTranscriptionWorker()
        worker._speaker_processor = mock_proc
        worker._speaker_mode = "identify"
        worker._speaker_cluster = cluster
        worker._speech_buffer = [np.zeros(16000, dtype=np.int16)]
        worker._audio_cfg = {"sample_rate": 16000}
        worker._transcription_task_count = 0
        worker._transcription_queue = queue.Queue(maxsize=10)

        worker._submit_speech()

        assert worker._transcription_queue.qsize() == 1
        item = worker._transcription_queue.get_nowait()
        _, speaker_id, speaker_confidence = item
        assert speaker_id == "unknown"
        assert speaker_confidence == 0.15
