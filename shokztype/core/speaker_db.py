"""Speaker embedding database — JSON-based CRUD for voice prints."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class SpeakerDB:
    """Manages speaker embeddings with JSON persistence."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._speakers: Dict[str, Dict[str, Any]] = {}
        self._auto_speakers: Dict[str, Dict[str, Any]] = {}
        self._auto_counter = 0
        self.load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enroll(self, name: str, embedding: np.ndarray) -> None:
        """Add an embedding for a speaker. Updates centroid automatically."""
        emb_list = embedding.tolist()
        if name in self._speakers:
            entry = self._speakers[name]
            entry["embeddings"].append(emb_list)
            entry["sample_count"] += 1
        else:
            entry = {
                "embeddings": [emb_list],
                "centroid": emb_list,
                "registered_at": datetime.now().isoformat(),
                "sample_count": 1,
            }
            self._speakers[name] = entry
        # Recompute centroid
        all_embs = np.array(entry["embeddings"], dtype=np.float32)
        mean_emb = np.mean(all_embs, axis=0)
        norm = np.linalg.norm(mean_emb)
        if norm > 1e-8:
            mean_emb = mean_emb / norm
        entry["centroid"] = mean_emb.tolist()
        self.save()
        logger.info("Enrolled speaker '%s' (%d samples)", name, entry["sample_count"])

    def update_centroid(
        self, name: str, embedding: np.ndarray, max_embeddings: int = 50
    ) -> bool:
        """Incrementally add an embedding and recompute L2-normalized centroid.

        Evicts the oldest embedding if count exceeds max_embeddings.
        Returns True if speaker was found and updated.
        """
        entry = self._speakers.get(name)
        if entry is None:
            return False

        entry["embeddings"].append(embedding.tolist())
        entry["sample_count"] += 1

        # Evict oldest if over limit
        while len(entry["embeddings"]) > max_embeddings:
            entry["embeddings"].pop(0)

        # Recompute L2-normalized centroid
        all_embs = np.array(entry["embeddings"], dtype=np.float32)
        mean_emb = np.mean(all_embs, axis=0)
        norm = np.linalg.norm(mean_emb)
        if norm > 1e-8:
            mean_emb = mean_emb / norm
        entry["centroid"] = mean_emb.tolist()

        self.save()
        logger.debug(
            "Updated centroid for '%s' (%d embeddings)",
            name, len(entry["embeddings"]),
        )
        return True

    def remove(self, name: str) -> bool:
        """Remove a speaker. Returns True if found and removed."""
        removed = self._speakers.pop(name, None) or self._auto_speakers.pop(name, None)
        if removed:
            self.save()
            logger.info("Removed speaker '%s'", name)
            return True
        return False

    def match(
        self, embedding: np.ndarray, threshold: float = 0.65
    ) -> Tuple[Optional[str], float]:
        """Find the best matching speaker by cosine similarity.

        Returns (speaker_name, score). If no match >= threshold, returns (None, best_score).
        """
        all_entries = {**self._speakers, **self._auto_speakers}
        if not all_entries:
            return None, 0.0

        query = embedding / (np.linalg.norm(embedding) + 1e-8)
        best_name: Optional[str] = None
        best_score = -1.0

        for name, entry in all_entries.items():
            if not entry.get("embeddings"):  # 跳过未完成录入的占位档案
                continue
            centroid = np.array(entry["centroid"], dtype=np.float32)
            centroid = centroid / (np.linalg.norm(centroid) + 1e-8)
            score = float(np.dot(query, centroid))
            if score > best_score:
                best_score = score
                best_name = name

        if best_score >= threshold:
            return best_name, best_score
        return None, best_score

    def match_top2(
        self, embedding: np.ndarray
    ) -> list[tuple[str, float]]:
        """Return up to 2 best matches sorted by cosine similarity (descending).

        Each entry is (speaker_name, score). Returns empty list if no speakers.
        """
        all_entries = {**self._speakers, **self._auto_speakers}
        if not all_entries:
            return []

        query = embedding / (np.linalg.norm(embedding) + 1e-8)
        scored: list[tuple[str, float]] = []

        for name, entry in all_entries.items():
            if not entry.get("embeddings"):
                continue
            centroid = np.array(entry["centroid"], dtype=np.float32)
            centroid = centroid / (np.linalg.norm(centroid) + 1e-8)
            score = float(np.dot(query, centroid))
            scored.append((name, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:2]

    def rename(self, old_name: str, new_name: str) -> bool:
        """Rename a speaker (typically auto-clustered ones)."""
        for store in (self._speakers, self._auto_speakers):
            if old_name in store:
                store[new_name] = store.pop(old_name)
                self.save()
                logger.info("Renamed speaker '%s' -> '%s'", old_name, new_name)
                return True
        return False

    def add_auto_speaker(self, embedding: np.ndarray) -> str:
        """Create a new auto-detected speaker. Returns assigned name."""
        self._auto_counter += 1
        name = f"speaker_{self._auto_counter:03d}"
        emb_list = embedding.tolist()
        self._auto_speakers[name] = {
            "embeddings": [emb_list],
            "centroid": emb_list,
            "registered_at": datetime.now().isoformat(),
            "sample_count": 1,
        }
        self.save()
        logger.info("Auto-created speaker '%s'", name)
        return name

    def list_speakers(self) -> List[str]:
        """List all registered speaker names (manual + auto)."""
        return list(self._speakers.keys()) + list(self._auto_speakers.keys())

    def list_manual_speakers(self) -> List[str]:
        """List only manually registered speaker names."""
        return list(self._speakers.keys())

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        data = {
            "speakers": self._speakers,
            "auto_speakers": self._auto_speakers,
            "auto_counter": self._auto_counter,
        }
        tmp_path = self._db_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self._db_path)

    def load(self) -> None:
        if not os.path.exists(self._db_path):
            logger.info("Speaker DB not found at '%s', starting empty", self._db_path)
            return
        try:
            with open(self._db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._speakers = data.get("speakers", {})
            self._auto_speakers = data.get("auto_speakers", {})
            self._auto_counter = data.get("auto_counter", 0)
            total = len(self._speakers) + len(self._auto_speakers)
            logger.info("Loaded speaker DB: %d speakers", total)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load speaker DB: %s", exc)
