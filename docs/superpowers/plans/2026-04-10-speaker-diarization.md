# Speaker Diarization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unsupervised speaker diarization mode (online incremental clustering) and remove the unused VAD-based enroll mode.

**Architecture:** New `SpeakerCluster` class performs online clustering using the existing CAM++ embedding extractor. Each VAD speech segment gets an embedding, which is assigned to an existing cluster or creates a new one. The existing identify/filter modes and manual enrollment are preserved unchanged.

**Tech Stack:** Python, numpy (cosine similarity), existing CAM++ model via `SpeakerProcessor.extract_embedding()`, NiceGUI web UI.

**Spec:** `docs/superpowers/specs/2026-04-10-speaker-diarization-design.md`

---

### Task 1: Create `SpeakerCluster` with TDD

**Files:**
- Create: `app/speaker_cluster.py`
- Create: `tests/test_speaker_cluster.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_speaker_cluster.py
import numpy as np
import pytest

from app.speaker_cluster import SpeakerCluster


def _random_embedding(seed: int) -> np.ndarray:
    """Generate a deterministic 192-dim embedding."""
    rng = np.random.RandomState(seed)
    emb = rng.randn(192).astype(np.float32)
    emb = emb / np.linalg.norm(emb)
    return emb


def _similar_embedding(base: np.ndarray, noise: float = 0.05) -> np.ndarray:
    """Generate an embedding similar to base (high cosine similarity)."""
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
        emb2 = _random_embedding(2)  # very different
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
        # After reset, counter resets too
        name = cluster.assign(_random_embedding(3))
        assert name == "说话人1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_speaker_cluster.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.speaker_cluster'`

- [ ] **Step 3: Implement SpeakerCluster**

```python
# app/speaker_cluster.py
"""Online speaker clustering — assigns embeddings to speaker clusters
without requiring pre-registration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ClusterEntry:
    embeddings: list = field(default_factory=list)  # list of np.ndarray
    centroid: np.ndarray = field(default_factory=lambda: np.zeros(192, dtype=np.float32))
    count: int = 0


class SpeakerCluster:
    """Online incremental speaker clustering using cosine similarity."""

    def __init__(self, threshold: float = 0.45) -> None:
        self._clusters: dict[str, ClusterEntry] = {}
        self._threshold = threshold
        self._counter = 0

    def assign(self, embedding: np.ndarray) -> str:
        """Assign an embedding to an existing cluster or create a new one.

        Returns the cluster name (e.g. '说话人1').
        """
        # L2-normalize the query embedding
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
            # Assign to existing cluster and update centroid
            entry = self._clusters[best_name]
            entry.embeddings.append(embedding)
            entry.count += 1
            # Recompute centroid as L2-normalized mean
            mean_emb = np.mean(entry.embeddings, axis=0)
            mean_norm = np.linalg.norm(mean_emb)
            if mean_norm > 1e-8:
                mean_emb = mean_emb / mean_norm
            entry.centroid = mean_emb
            logger.info(
                "Diarize: assigned to '%s' (score=%.4f, count=%d)",
                best_name, best_score, entry.count,
            )
            return best_name

        # Create new cluster
        self._counter += 1
        new_name = f"说话人{self._counter}"
        self._clusters[new_name] = ClusterEntry(
            embeddings=[embedding],
            centroid=embedding.copy(),
            count=1,
        )
        logger.info(
            "Diarize: new speaker '%s' (best_existing_score=%.4f)",
            new_name, best_score,
        )
        return new_name

    def rename(self, old_name: str, new_name: str) -> bool:
        """Rename a cluster. Returns False if old_name not found or new_name conflicts."""
        if old_name not in self._clusters:
            return False
        if new_name in self._clusters:
            return False
        self._clusters[new_name] = self._clusters.pop(old_name)
        return True

    def reset(self) -> None:
        """Clear all clusters (call when starting a new session)."""
        self._clusters.clear()
        self._counter = 0

    def get_speakers(self) -> list[dict]:
        """Return list of speaker info dicts: [{name, count}]."""
        return [
            {"name": name, "count": entry.count}
            for name, entry in self._clusters.items()
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_speaker_cluster.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/speaker_cluster.py tests/test_speaker_cluster.py
git commit -m "feat: add SpeakerCluster for online speaker diarization"
```

---

### Task 2: Remove enroll mode from `vad_worker.py`

**Files:**
- Modify: `app/vad_worker.py:38` (constructor — remove enroll state)
- Modify: `app/vad_worker.py:238-263` (delete enroll branch in `_submit_speech`)

- [ ] **Step 1: Remove enroll state from constructor**

In `app/vad_worker.py`, delete lines 65-69 (enroll state initialization):

```python
# DELETE these lines:
        # Enroll mode state
        spk_cfg = self.config.get("speaker", {})
        self._enroll_target = spk_cfg.get("enroll_target", "")
        self._enroll_samples = spk_cfg.get("enroll_samples", 5)
        self._enroll_count = 0
```

- [ ] **Step 2: Remove enroll branch from `_submit_speech`**

In `app/vad_worker.py`, delete lines 238-263 (the entire enroll block):

```python
# DELETE this entire block:
        # Enroll mode: store embedding and skip transcription
        if self._speaker_mode == "enroll" and self._speaker_processor:
            if not self._enroll_target:
                logger.error("Enroll mode but no enroll_target configured")
                return
            try:
                embedding = self._speaker_processor.extract_embedding(combined)
                self._speaker_processor.db.enroll(self._enroll_target, embedding)
                self._enroll_count += 1
                logger.info(
                    "Enroll: stored sample %d/%d for '%s'",
                    self._enroll_count,
                    self._enroll_samples,
                    self._enroll_target,
                )
                if self._enroll_count >= self._enroll_samples:
                    logger.info(
                        "Enroll complete: %d samples for '%s'. Switching to filter mode.",
                        self._enroll_count,
                        self._enroll_target,
                    )
                    self._speaker_mode = "filter"
                    self._enroll_count = 0
            except Exception as exc:
                logger.error("Enroll embedding extraction failed: %s", exc)
            return
```

- [ ] **Step 3: Verify existing tests still pass**

Run: `python -m pytest tests/ -v -k "vad" --timeout=30`
Expected: Existing VAD tests pass (any enroll-specific tests should be removed if they exist)

- [ ] **Step 4: Commit**

```bash
git add app/vad_worker.py
git commit -m "refactor: remove enroll mode from VadTranscriptionWorker"
```

---

### Task 3: Add diarize mode to `vad_worker.py`

**Files:**
- Modify: `app/vad_worker.py:32-39` (add `speaker_cluster` param to constructor)
- Modify: `app/vad_worker.py` (`_submit_speech` — add diarize branch)

- [ ] **Step 1: Add `speaker_cluster` parameter to constructor**

In `app/vad_worker.py`, modify the `__init__` signature to add `speaker_cluster` parameter:

```python
    def __init__(
        self,
        config_path: Optional[str] = None,
        on_result: Optional[Callable[[TranscriptionResult], None]] = None,
        audio_source: Optional[AudioSource] = None,
        speaker_processor: Optional[object] = None,
        speaker_mode: str = "off",
        speaker_cluster: Optional[object] = None,
    ) -> None:
```

After line 63 (`self._speaker_mode = speaker_mode`), add:

```python
        self._speaker_cluster = speaker_cluster
```

- [ ] **Step 2: Add diarize branch to `_submit_speech`**

In `_submit_speech`, after the `duration_s` log line and before the existing speaker recognition block, add:

```python
        # Diarize mode: online clustering (no pre-registration needed)
        if self._speaker_mode == "diarize" and self._speaker_cluster and self._speaker_processor:
            try:
                embedding = self._speaker_processor.extract_embedding(combined)
                speaker_id = self._speaker_cluster.assign(embedding)
            except Exception as exc:
                logger.warning("Diarize embedding extraction failed: %s", exc)
                speaker_id = None
```

The full speaker block in `_submit_speech` should now read:

```python
        # Diarize mode: online clustering (no pre-registration needed)
        if self._speaker_mode == "diarize" and self._speaker_cluster and self._speaker_processor:
            try:
                embedding = self._speaker_processor.extract_embedding(combined)
                speaker_id = self._speaker_cluster.assign(embedding)
            except Exception as exc:
                logger.warning("Diarize embedding extraction failed: %s", exc)
                speaker_id = None

        # Speaker recognition (identify/filter modes)
        elif self._speaker_processor:
            if self._speaker_mode == "filter":
                ok, sid = self._speaker_processor.should_transcribe(combined)
                ...
```

Note the `elif` — diarize takes priority and skips identify/filter logic.

- [ ] **Step 3: Verify all tests pass**

Run: `python -m pytest tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add app/vad_worker.py
git commit -m "feat: add diarize mode to VadTranscriptionWorker"
```

---

### Task 4: Remove enroll config and add diarize to mode options

**Files:**
- Modify: `app/config.py:52-67` (remove enroll config keys)

- [ ] **Step 1: Remove enroll config keys**

In `app/config.py`, change the speaker config section from:

```python
    "speaker": {
        "enabled": False,
        "mode": "identify",       # "identify" | "filter" | "enroll" | "off"
        "model": "iic/speech_campplus_sv_zh-cn_16k-common",
        "threshold": 0.45,
        "db_path": "speaker_db.json",
        "auto_learn": False,
        "whitelist": [],
        # Voiceprint gate
        "incremental_learn": True,
        "incremental_margin": 0.10,
        "max_embeddings": 50,
        "enroll_target": "",
        "enroll_samples": 5,
        "min_enroll_samples": 3,
    },
```

To:

```python
    "speaker": {
        "enabled": False,
        "mode": "identify",       # "identify" | "filter" | "diarize" | "off"
        "model": "iic/speech_campplus_sv_zh-cn_16k-common",
        "threshold": 0.45,
        "db_path": "speaker_db.json",
        "auto_learn": False,
        "whitelist": [],
        # Voiceprint gate
        "incremental_learn": True,
        "incremental_margin": 0.10,
        "max_embeddings": 50,
    },
```

- [ ] **Step 2: Commit**

```bash
git add app/config.py
git commit -m "refactor: remove enroll config keys, add diarize to mode comment"
```

---

### Task 5: Update `main.py` — replace enroll with diarize

**Files:**
- Modify: `main.py:254-329` (`_choose_speaker_mode`)
- Modify: `main.py:440-455` (`_run_vad_mode`)

- [ ] **Step 1: Replace enroll menu option with diarize in `_choose_speaker_mode`**

Replace the speaker mode menu (lines 254-329) with:

```python
def _choose_speaker_mode(config):
    """交互选择声纹识别模式，返回 (mode_str, processor_or_None)"""
    print("\n  声纹识别:")
    print("  [1] 关闭（不使用声纹）")
    print("  [2] 识别模式（标注说话人）")
    print("  [3] 过滤模式（只转录指定人）")
    print("  [4] 说话人分离（自动区分不同说话人）")
    spk_choice = input("  输入 1/2/3/4: ").strip()

    if spk_choice not in ("2", "3", "4"):
        return "off", None

    # 加载声纹处理器
    try:
        from app.speaker import SpeakerProcessor
        config["speaker"]["enabled"] = True
        processor = SpeakerProcessor(config)
    except Exception as exc:
        logger.warning("声纹模型加载失败，退化为无声纹模式: %s", exc)
        return "off", None

    if spk_choice == "2":
        logger.info("声纹识别模式已启用")
        return "identify", processor

    if spk_choice == "4":
        logger.info("说话人分离模式已启用")
        return "diarize", processor

    # 过滤模式：选择白名单
    speakers = processor.db.list_manual_speakers()
    if not speakers:
        logger.warning("无已注册说话人，退化为识别模式")
        return "identify", processor

    print("\n  已注册说话人:")
    for i, name in enumerate(speakers, 1):
        print(f"  [{i}] {name}")
    sel = input("  输入要保留的编号（逗号分隔，如 1,2）: ").strip()
    whitelist = []
    for s in sel.split(","):
        s = s.strip()
        if s.isdigit() and 1 <= int(s) <= len(speakers):
            whitelist.append(speakers[int(s) - 1])
    if not whitelist:
        logger.warning("未选择白名单，退化为识别模式")
        return "identify", processor

    processor._whitelist = set(whitelist)
    logger.info("声纹过滤模式已启用，白名单: %s", whitelist)
    return "filter", processor
```

- [ ] **Step 2: Update `_run_vad_mode` to handle diarize**

Replace lines 440-456 of `_run_vad_mode`:

```python
def _run_vad_mode(args, config, output_method, append_newline, audio_source,
                  speaker_processor=None, speaker_mode="off") -> None:
    from app.vad_worker import VadTranscriptionWorker

    speaker_cluster = None
    if speaker_mode == "diarize":
        from app.speaker_cluster import SpeakerCluster
        threshold = config.get("speaker", {}).get("threshold", 0.45)
        speaker_cluster = SpeakerCluster(threshold=threshold)

    worker = VadTranscriptionWorker(
        config_path=args.config,
        on_result=None,
        audio_source=audio_source,
        speaker_processor=speaker_processor,
        speaker_mode=speaker_mode,
        speaker_cluster=speaker_cluster,
    )
    worker.on_result = _make_result_handler(output_method, append_newline, worker)
```

Note: the old enroll config override block (`if speaker_mode == "enroll": ...`) is deleted entirely.

- [ ] **Step 3: Verify CLI still works**

Run: `python main.py --help`
Expected: No import errors

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: replace enroll mode with diarize in CLI menu"
```

---

### Task 6: Update Web UI state and settings page

**Files:**
- Modify: `app/web/state.py:35` (update speaker_mode options, add speaker_cluster)
- Modify: `app/web/pages/settings.py:81-86` (replace enroll with diarize)

- [ ] **Step 1: Update `app/web/state.py`**

Change line 35:
```python
    speaker_mode: str = "off"  # "off" | "identify" | "filter" | "enroll"
```
To:
```python
    speaker_mode: str = "off"  # "off" | "identify" | "filter" | "diarize"
```

Add after line 51 (`speaker_processor`):
```python
    speaker_cluster: Optional[Any] = None
```

- [ ] **Step 2: Update `app/web/pages/settings.py`**

Change lines 81-86 from:
```python
        speaker_modes = [
            ('关闭', 'off'),
            ('识别', 'identify'),
            ('过滤', 'filter'),
            ('实时注册', 'enroll'),
        ]
```
To:
```python
        speaker_modes = [
            ('关闭', 'off'),
            ('识别', 'identify'),
            ('过滤', 'filter'),
            ('说话人分离', 'diarize'),
        ]
```

- [ ] **Step 3: Commit**

```bash
git add app/web/state.py app/web/pages/settings.py
git commit -m "feat: update web UI state and settings for diarize mode"
```

---

### Task 7: Update `audio_controls.py` to create `SpeakerCluster` for diarize mode

**Files:**
- Modify: `app/web/components/audio_controls.py:62-74` (`_ensure_worker`)

- [ ] **Step 1: Update `_ensure_worker` to handle diarize mode**

Replace the `_ensure_worker` function:

```python
def _ensure_worker():
    """Create the transcription worker if it doesn't exist yet."""
    if app_state.worker is not None:
        return
    _ensure_audio_source()
    if app_state.recording_mode == 'vad':
        from app.vad_worker import VadTranscriptionWorker

        speaker_cluster = None
        if app_state.speaker_mode == 'diarize':
            from app.speaker_cluster import SpeakerCluster
            threshold = app_state.config.get('speaker', {}).get('threshold', 0.45)
            speaker_cluster = SpeakerCluster(threshold=threshold)
            app_state.speaker_cluster = speaker_cluster

        app_state.worker = VadTranscriptionWorker(
            on_result=_on_transcription_result,
            audio_source=app_state.audio,
            speaker_processor=app_state.speaker_processor,
            speaker_mode=app_state.speaker_mode,
            speaker_cluster=speaker_cluster,
        )
    else:
        from app.transcribe import TranscriptionWorker
        app_state.worker = TranscriptionWorker(
            on_result=_on_transcription_result,
            audio_source=app_state.audio,
        )
```

- [ ] **Step 2: Reset cluster on stop**

In `_cleanup_worker`, add cluster reset:

```python
def _cleanup_worker():
    """Destroy the current worker and audio source so a fresh one is
    created next time (e.g. when the user changes mode or source)."""
    if app_state.worker is not None:
        try:
            app_state.worker.cleanup()
        except Exception:
            pass
        app_state.worker = None
    if app_state.audio is not None:
        try:
            app_state.audio.stop()
        except Exception:
            pass
        app_state.audio = None
    if app_state.speaker_cluster is not None:
        app_state.speaker_cluster.reset()
        app_state.speaker_cluster = None
```

- [ ] **Step 3: Commit**

```bash
git add app/web/components/audio_controls.py
git commit -m "feat: create SpeakerCluster in web UI for diarize mode"
```

---

### Task 8: Remove enrollment UI from speakers page

**Files:**
- Modify: `app/web/pages/speakers.py:23-28` (delete enrollment state globals)
- Modify: `app/web/pages/speakers.py:77-163` (delete `_stop_enrollment`, `_start_enrollment`)
- Modify: `app/web/pages/speakers.py:361-451` (delete `_enrollment_card`)
- Modify: `app/web/pages/speakers.py` (remove enrollment card usage from `speakers_page`)

- [ ] **Step 1: Delete enrollment state and functions**

In `app/web/pages/speakers.py`:

1. Delete the module-level enrollment state (lines 23-28):
```python
# DELETE:
_enrollment_active = False
_enrollment_name = ''
_enrollment_target_samples = 5
_enrollment_collected = 0
_enrollment_worker = None
```

2. Delete `_stop_enrollment` function (lines 77-88)

3. Delete `_start_enrollment` function (lines 91-162)

4. Delete `_enrollment_card` function (lines 361-451)

5. In the `speakers_page()` function, remove the conditional that shows `_enrollment_card()` when `_enrollment_active` is True.

- [ ] **Step 2: Verify page still renders**

Run: `python -c "from app.web.pages.speakers import speakers_page; print('OK')"`
Expected: `OK` (no import errors)

- [ ] **Step 3: Commit**

```bash
git add app/web/pages/speakers.py
git commit -m "refactor: remove enrollment UI from speakers page"
```

---

### Task 9: Add diarize speaker list and rename UI to speakers page

**Files:**
- Modify: `app/web/pages/speakers.py` (add diarize section)

- [ ] **Step 1: Add diarize speakers section**

At the end of the `speakers_page()` function (after the registered speakers card), add a new card for diarize session speakers:

```python
    # ------------------------------------------------------------------
    # Card: Diarize Session Speakers (shown when diarize mode is active)
    # ------------------------------------------------------------------
    if app_state.speaker_mode == 'diarize' and app_state.speaker_cluster is not None:
        with ui.element('div').style(
            f'background: {CARD_BG}; border-radius: 12px; padding: 20px 24px; '
            f'margin-bottom: 16px;'
        ):
            ui.label('当前会话说话人').style(
                f'color: {TEXT_MAIN}; font-size: 16px; font-weight: 600; '
                f'margin-bottom: 12px;'
            )

            speakers = app_state.speaker_cluster.get_speakers()
            if not speakers:
                ui.label('尚未检测到说话人，请开始转写').style(
                    f'color: {TEXT_SEC}; font-size: 13px; font-style: italic;'
                )
            else:
                for spk in speakers:
                    with ui.row().classes('items-center gap-3 w-full').style(
                        'padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.06);'
                    ):
                        # Color dot
                        from app.web.components.transcript import _color_for_speaker
                        color = _color_for_speaker(spk['name'])
                        ui.element('div').style(
                            f'width: 12px; height: 12px; border-radius: 50%; '
                            f'background: {color}; flex-shrink: 0;'
                        )

                        # Name
                        ui.label(spk['name']).style(
                            f'color: {TEXT_MAIN}; font-size: 14px; flex: 1;'
                        )

                        # Count badge
                        ui.label(f'{spk["count"]} 段').style(
                            f'color: {TEXT_SEC}; font-size: 12px;'
                        )

                        # Rename button
                        def _do_rename(old_name=spk['name']):
                            async def _handle_rename():
                                result = await ui.run_javascript(
                                    f'prompt("将 {old_name} 改名为：", "")'
                                )
                                if result and result.strip():
                                    new_name = result.strip()
                                    if app_state.speaker_cluster.rename(old_name, new_name):
                                        # Update existing transcription results
                                        for r in app_state.transcription_results:
                                            if r.get('speaker') == old_name:
                                                r['speaker'] = new_name
                                        ui.notify(f'已改名: {old_name} → {new_name}', type='positive')
                                        ui.navigate.to('/speakers')
                                    else:
                                        ui.notify('改名失败（名称冲突或不存在）', type='negative')
                            _handle_rename()

                        ui.button(icon='edit', on_click=_do_rename).props(
                            'flat dense round'
                        ).style(f'color: {ACCENT};')

        # Auto-refresh timer to update speaker list
        def _refresh_diarize_speakers():
            pass  # Page will refresh on navigate; timer is lightweight placeholder

        ui.timer(2.0, lambda: ui.navigate.to('/speakers') if app_state.speaker_cluster and
                 len(app_state.speaker_cluster.get_speakers()) != len(speakers) else None)
```

- [ ] **Step 2: Verify page renders with diarize mode**

Run: `python -c "from app.web.pages.speakers import speakers_page; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/web/pages/speakers.py
git commit -m "feat: add diarize speaker list with rename UI to speakers page"
```

---

### Task 10: End-to-end verification

**Files:** None (verification only)

- [ ] **Step 1: Run all unit tests**

Run: `python -m pytest tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 2: Verify CLI help**

Run: `python main.py --help`
Expected: No import errors

- [ ] **Step 3: Verify web UI starts**

Run: `python main.py --web` (or however the web flag works)
Expected: NiceGUI server starts on port 8080 without errors

- [ ] **Step 4: Verify no references to deleted enroll mode remain**

Run: `grep -rn "enroll" app/ main.py --include="*.py" | grep -v "__pycache__" | grep -v "speaker_enroll"`
Expected: Only `speaker_enroll.py` references remain (the CLI tool, which is kept). No references to enroll mode in `vad_worker.py`, `main.py`, `config.py`, or web UI files.

- [ ] **Step 5: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: cleanup after speaker diarization implementation"
```
