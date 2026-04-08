"""Tests for SpeakerDB voiceprint gate features."""

import json
import os
import numpy as np
import pytest
from app.speaker_db import SpeakerDB


@pytest.fixture
def db(tmp_path):
    return SpeakerDB(str(tmp_path / "test_speakers.json"))


def test_enroll_centroid_is_l2_normalized(db):
    """Centroid should be L2-normalized after enroll."""
    emb = np.random.randn(192).astype(np.float32)
    db.enroll("alice", emb)
    centroid = np.array(db._speakers["alice"]["centroid"], dtype=np.float32)
    norm = np.linalg.norm(centroid)
    assert abs(norm - 1.0) < 1e-5, f"Centroid norm should be ~1.0, got {norm}"


def test_update_centroid_adds_embedding(db):
    """update_centroid should add new embedding and recompute centroid."""
    emb1 = np.array([1.0, 0.0, 0.0] + [0.0] * 189, dtype=np.float32)
    db.enroll("alice", emb1)
    old_count = db._speakers["alice"]["sample_count"]

    emb2 = np.array([0.0, 1.0, 0.0] + [0.0] * 189, dtype=np.float32)
    db.update_centroid("alice", emb2, max_embeddings=50)

    assert db._speakers["alice"]["sample_count"] == old_count + 1
    assert len(db._speakers["alice"]["embeddings"]) == 2
    centroid = np.array(db._speakers["alice"]["centroid"], dtype=np.float32)
    assert abs(np.linalg.norm(centroid) - 1.0) < 1e-5


def test_update_centroid_evicts_oldest(db):
    """When embeddings exceed max_embeddings, oldest should be evicted."""
    for i in range(5):
        emb = np.random.randn(192).astype(np.float32)
        db.enroll("alice", emb)

    new_emb = np.random.randn(192).astype(np.float32)
    db.update_centroid("alice", new_emb, max_embeddings=5)

    assert len(db._speakers["alice"]["embeddings"]) == 5
    assert db._speakers["alice"]["sample_count"] == 6


def test_match_top2_returns_two_results(db):
    """match_top2 should return best and second-best matches."""
    emb_a = np.array([1.0, 0.0] + [0.0] * 190, dtype=np.float32)
    emb_b = np.array([0.0, 1.0] + [0.0] * 190, dtype=np.float32)
    db.enroll("alice", emb_a)
    db.enroll("bob", emb_b)

    query = np.array([0.9, 0.1] + [0.0] * 190, dtype=np.float32)
    top2 = db.match_top2(query)

    assert len(top2) == 2
    assert top2[0][0] == "alice"
    assert top2[1][0] == "bob"
    assert top2[0][1] > top2[1][1]


def test_match_top2_single_speaker(db):
    """match_top2 with only one speaker returns list of length 1."""
    emb = np.random.randn(192).astype(np.float32)
    db.enroll("alice", emb)

    query = np.random.randn(192).astype(np.float32)
    top2 = db.match_top2(query)

    assert len(top2) == 1
    assert top2[0][0] == "alice"
