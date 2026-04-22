"""Abstract base class for audio sources."""

from __future__ import annotations

import queue
from abc import ABC, abstractmethod

import numpy as np


class AudioSource(ABC):
    """Any object that produces audio frames into a queue."""

    @property
    @abstractmethod
    def queue(self) -> "queue.Queue[np.ndarray]":
        """Return the queue that receives int16 audio frames."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Begin producing audio frames."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop producing audio frames."""
        ...

    @abstractmethod
    def flush(self) -> None:
        """Discard all queued frames."""
        ...
