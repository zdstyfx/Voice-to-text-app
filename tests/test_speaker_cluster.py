import numpy as np
import pytest

from app.speaker_cluster import SpeakerCluster


def _random_embedding(seed: int) -> np.ndarray:
    rng = np.random.RandomState(seed)
    emb = rng.randn(192).astype(np.float32)
    emb = emb / np.linalg.norm(emb)
    return emb


def _similar_embedding(base: np.ndarray, noise: float = 0.05) -> np.ndarray:
    rng = np.random.RandomState(42)
    noisy = base + rng.randn(192).astype(np.float32) * noise
    noisy = noisy / np.linalg.norm(noisy)
    return noisy


class TestAssign:
    def test_first_embedding_creates_speaker_1(self):
        cluster = SpeakerCluster(threshold=0.45)
        emb = _random_embedding(1)
        name = cluster.assign(emb)
        assert name == "说话人1"

    def test_similar_embedding_same_speaker(self):
        cluster = SpeakerCluster(threshold=0.45)
        emb1 = _random_embedding(1)
        emb2 = _similar_embedding(emb1, noise=0.05)
        name1 = cluster.assign(emb1)
        name2 = cluster.assign(emb2)
        assert name1 == name2 == "说话人1"

    def test_different_embedding_new_speaker(self):
        cluster = SpeakerCluster(threshold=0.45)
        emb1 = _random_embedding(1)
        emb2 = _random_embedding(2)
        name1 = cluster.assign(emb1)
        name2 = cluster.assign(emb2)
        assert name1 == "说话人1"
        assert name2 == "说话人2"

    def test_centroid_updates_on_assign(self):
        cluster = SpeakerCluster(threshold=0.45)
        emb1 = _random_embedding(1)
        cluster.assign(emb1)
        assert cluster._clusters["说话人1"].count == 1
        emb2 = _similar_embedding(emb1, noise=0.05)
        cluster.assign(emb2)
        assert cluster._clusters["说话人1"].count == 2


class TestRename:
    def test_rename_success(self):
        cluster = SpeakerCluster(threshold=0.45)
        cluster.assign(_random_embedding(1))
        assert cluster.rename("说话人1", "张三") is True
        assert "张三" in cluster._clusters
        assert "说话人1" not in cluster._clusters

    def test_rename_nonexistent(self):
        cluster = SpeakerCluster(threshold=0.45)
        assert cluster.rename("不存在", "张三") is False

    def test_rename_conflict(self):
        cluster = SpeakerCluster(threshold=0.45)
        cluster.assign(_random_embedding(1))
        cluster.assign(_random_embedding(2))
        assert cluster.rename("说话人1", "说话人2") is False


class TestGetSpeakersAndReset:
    def test_get_speakers(self):
        cluster = SpeakerCluster(threshold=0.45)
        cluster.assign(_random_embedding(1))
        cluster.assign(_random_embedding(2))
        speakers = cluster.get_speakers()
        assert len(speakers) == 2
        names = [s["name"] for s in speakers]
        assert "说话人1" in names
        assert "说话人2" in names

    def test_reset(self):
        cluster = SpeakerCluster(threshold=0.45)
        cluster.assign(_random_embedding(1))
        cluster.reset()
        assert cluster.get_speakers() == []
        name = cluster.assign(_random_embedding(3))
        assert name == "说话人1"
