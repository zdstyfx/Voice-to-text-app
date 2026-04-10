"""Online speaker clustering — assigns embeddings to speaker clusters
without requiring pre-registration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ClusterEntry:
    embeddings: list = field(default_factory=list)
    centroid: np.ndarray = field(default_factory=lambda: np.zeros(192, dtype=np.float32))
    count: int = 0


class SpeakerCluster:
    """Online incremental speaker clustering using cosine similarity."""

    def __init__(self, threshold: float = 0.45) -> None:
        self._clusters: dict[str, ClusterEntry] = {}
        self._threshold = threshold
        self._counter = 0

    def assign(self, embedding: np.ndarray) -> str:
        norm = np.linalg.norm(embedding)
        if norm > 1e-8:
            embedding = embedding / norm

        best_name: str | None = None
        best_score = -1.0

        for name, entry in self._clusters.items():
            score = float(np.dot(embedding, entry.centroid))
            if score > best_score:
                best_score = score
                best_name = name

        if best_name is not None and best_score >= self._threshold:
            entry = self._clusters[best_name]
            entry.embeddings.append(embedding)
            entry.count += 1
            mean_emb = np.mean(entry.embeddings, axis=0)
            mean_norm = np.linalg.norm(mean_emb)
            if mean_norm > 1e-8:
                mean_emb = mean_emb / mean_norm
            entry.centroid = mean_emb
            logger.info("Diarize: assigned to '%s' (score=%.4f, count=%d)", best_name, best_score, entry.count)
            return best_name

        self._counter += 1
        new_name = f"说话人{self._counter}"
        self._clusters[new_name] = ClusterEntry(
            embeddings=[embedding],
            centroid=embedding.copy(),
            count=1,
        )
        logger.info("Diarize: new speaker '%s' (best_existing_score=%.4f)", new_name, best_score)
        return new_name

    def rename(self, old_name: str, new_name: str) -> bool:
        if old_name not in self._clusters:
            return False
        if new_name in self._clusters:
            return False
        self._clusters[new_name] = self._clusters.pop(old_name)
        return True

    def reset(self) -> None:
        self._clusters.clear()
        self._counter = 0

    def get_speakers(self) -> list[dict]:
        return [
            {"name": name, "count": entry.count}
            for name, entry in self._clusters.items()
        ]
