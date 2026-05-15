"""声纹过滤模块。

插入帧流链路中，每 2 秒验证一次说话人，通过的帧转发，不通过的丢弃。
录音本身不受影响——只过滤帧，不阻断录音。

帧流：
  帧源 → SpeakerGate._filter_loop → output_queue → 转录模块
"""

import logging
import queue
import threading
import time
from typing import Any, Optional

import numpy as np

from shokztype.web.services.event_bus import EventBus
from shokztype.web.web_config import get_config

logger = logging.getLogger(__name__)

_VERIFY_INTERVAL_FRAMES = 50  # 50 帧 × 20ms = 1 秒（减小以降低过渡批次丢失）


class SpeakerGate:

    def __init__(self, bus: EventBus, input_queue: queue.Queue, audio=None) -> None:
        self._bus = bus
        self._input_queue = input_queue
        self._audio = audio  # 非 None 时由 SpeakerGate 管 audio.start()/stop()
        self.output_queue: queue.Queue = queue.Queue(maxsize=200)
        self._speaker_processor = None
        self._filter_thread: Optional[threading.Thread] = None
        self._filter_running = threading.Event()
        self.last_approval_time: float = 0.0  # 最近一次声纹验证通过的时间

        self._init_processor()

        bus.on("start", self._on_start)
        bus.on("stop", self._on_stop)
        bus.on("done", self._on_done)

    def cleanup(self) -> None:
        self._filter_running.clear()
        if self._filter_thread and self._filter_thread.is_alive():
            self._filter_thread.join(timeout=3.0)
        self._bus.off("start", self._on_start)
        self._bus.off("stop", self._on_stop)
        self._bus.off("done", self._on_done)

    def _init_processor(self) -> None:
        from shokztype.web.services.voiceprint_manager import get_speaker_processor
        self._speaker_processor = get_speaker_processor()

    # --- 生命周期（跟随录音） ---

    def _on_start(self, _: Any) -> None:
        # 如果 SpeakerGate 直接读 audio.queue（热键模式），由它管 audio 生命周期
        if self._audio is not None:
            self._bus.emit("state", {"status": "recording"})
            self._audio.start()
        self._filter_running.set()
        self._filter_thread = threading.Thread(
            target=self._filter_loop, daemon=True, name="SpeakerFilter",
        )
        self._filter_thread.start()

    def _on_stop(self, _: Any) -> None:
        self._filter_running.clear()
        if self._audio is not None:
            self._audio.stop()
        # join 在后台线程执行，避免阻塞 EventBus 派发
        t = self._filter_thread
        self._filter_thread = None
        if t is not None and t.is_alive():
            threading.Thread(target=t.join, args=(3.0,), daemon=True).start()

    def _on_done(self, _: Any) -> None:
        # stop 里已经 join 过了，这里只做兜底
        self._filter_running.clear()

    # --- 帧过滤循环 ---

    def _filter_loop(self) -> None:
        logger.info("声纹过滤已启动")
        batch: list[np.ndarray] = []

        while self._filter_running.is_set():
            try:
                frame = self._input_queue.get(timeout=0.05)
            except Exception:
                continue

            if not isinstance(frame, np.ndarray):
                frame = np.frombuffer(frame, dtype=np.int16)
            batch.append(frame)

            if len(batch) >= _VERIFY_INTERVAL_FRAMES:
                self._process_batch(batch)
                batch = []

        # 退出前：剩余帧走声纹验证后再转发
        if batch:
            self._process_batch(batch)

        logger.info("声纹过滤已停止")

    def _process_batch(self, frames: list[np.ndarray]) -> None:
        """验证一批帧（2 秒），通过则转发，不通过则丢弃。"""
        config = get_config()
        vp_cfg = config.get("voiceprint", {})

        if not vp_cfg.get("enabled") or not vp_cfg.get("activeProfiles"):
            self._forward(frames)
            return

        if self._speaker_processor is None:
            self._init_processor()
        sp = self._speaker_processor
        if sp is None:
            self._forward(frames)
            return

        combined = np.concatenate(frames)
        try:
            sp._whitelist = set(vp_cfg.get("activeProfiles", []))
            ok, speaker_id = sp.should_transcribe(combined)
        except Exception as e:
            logger.warning("声纹验证异常，放行: %s", e)
            self._forward(frames)
            return

        if ok:
            self._forward(frames)
        else:
            logger.info("声纹过滤: 丢弃 %d 帧 (说话人: %s)，发送静音维持流连续性", len(frames), speaker_id)
            self._forward_silence(len(frames))

    def _forward(self, frames: list[np.ndarray]) -> None:
        self.last_approval_time = time.time()
        for frame in frames:
            try:
                self.output_queue.put_nowait(frame)
            except queue.Full:
                break

    def _forward_silence(self, n_frames: int) -> None:
        """发送静音帧替代丢弃帧，维持流式 ASR 的音频连续性。"""
        silence = np.zeros(320, dtype=np.int16)  # 16kHz × 20ms
        for _ in range(n_frames):
            try:
                self.output_queue.put_nowait(silence)
            except queue.Full:
                break
