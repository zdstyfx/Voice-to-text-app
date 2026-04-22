"""Tests for AudioSource ABC."""

import queue

import numpy as np
import pytest

from shokztype.core.audio_source import AudioSource


def test_cannot_instantiate_directly():
    with pytest.raises(TypeError):
        AudioSource()


class _DummySource(AudioSource):
    def __init__(self):
        self._q: queue.Queue[np.ndarray] = queue.Queue()

    @property
    def queue(self) -> queue.Queue[np.ndarray]:
        return self._q

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def flush(self) -> None:
        while not self._q.empty():
            self._q.get_nowait()


def test_concrete_subclass_can_instantiate():
    src = _DummySource()
    assert isinstance(src, AudioSource)
    assert isinstance(src.queue, queue.Queue)


def test_audio_capture_is_audio_source():
    from shokztype.core.audio_capture import AudioCapture
    assert issubclass(AudioCapture, AudioSource)
