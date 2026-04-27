"""录音管线组装器。

职责：
- 根据配置组装唤醒模块 + 转录模块，通过 EventBus 连接
- 管理共享资源：overlay、状态推送、音频设备、LLM 输出管线
- 提供 init/start/stop/restart 生命周期 API
"""

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import threading

import sounddevice as sd

from shokztype.core import type_text
from shokztype.core.audio_capture import AudioCapture
from shokztype.web.web_config import get_config, update_config
from shokztype.web.services.text_pipeline import process_text
from shokztype.web.services.event_bus import bus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 管线实例（全局）
# ---------------------------------------------------------------------------

_wakeup = None   # HotkeyWakeup | VadKwsWakeup
_transcriber = None  # StreamTranscriber | BatchTranscriber
_audio: AudioCapture | None = None

_loop: asyncio.AbstractEventLoop | None = None
_recording = False
_ready = False
_init_error: str | None = None
_wakeup_method: str = "hotkey"
_active_device_id: str | None = None
_preferred_endpoint_id: str | None = None
_device_switch_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 系统浮窗（独立进程，UDP 通信）
# ---------------------------------------------------------------------------

_OVERLAY_PORT = 9123
_overlay_proc: subprocess.Popen | None = None
_overlay_sock: socket.socket | None = None


def _start_overlay():
    global _overlay_proc, _overlay_sock
    try:
        if getattr(sys, 'frozen', False):
            # PyInstaller 打包模式：用 exe 自身的 --overlay 入口
            cmd = [sys.executable, "--overlay", "--port", str(_OVERLAY_PORT)]
        else:
            # 开发模式：直接跑 overlay_process.py
            script = os.path.join(os.path.dirname(__file__), "overlay_process.py")
            cmd = [sys.executable, script, "--port", str(_OVERLAY_PORT)]
        _overlay_proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _overlay_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        logger.info("浮窗进程已启动 (PID=%d)", _overlay_proc.pid)
    except Exception as e:
        logger.warning("浮窗启动失败: %s", e)


def _stop_overlay():
    global _overlay_proc, _overlay_sock
    if _overlay_proc:
        try:
            _overlay_proc.terminate()
        except Exception:
            pass
        _overlay_proc = None
    if _overlay_sock:
        _overlay_sock.close()
        _overlay_sock = None


def _push_overlay(status: str, text: str | None = None):
    if _overlay_sock is None:
        return
    try:
        msg = json.dumps({"status": status, "text": text}, ensure_ascii=False)
        _overlay_sock.sendto(msg.encode("utf-8"), ("127.0.0.1", _OVERLAY_PORT))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 统一状态管理：单一状态源 + 双通道推送（overlay UDP + 前端 SSE）
# ---------------------------------------------------------------------------

_ui_state: dict = {"status": "loading", "text": None}
_state_clients: list[asyncio.Queue] = []


async def state_subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _state_clients.append(queue)
    return queue


def state_unsubscribe(queue: asyncio.Queue) -> None:
    if queue in _state_clients:
        _state_clients.remove(queue)


def get_ui_state() -> dict:
    return dict(_ui_state)


def _set_state(status: str, text: str | None = None):
    """唯一的状态变更入口。"""
    _ui_state["status"] = status
    _ui_state["text"] = text
    _push_overlay(status, text)
    msg = json.dumps({"event": "state", "status": status, "text": text}, ensure_ascii=False)
    for queue in list(_state_clients):
        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            pass


# ---------------------------------------------------------------------------
# EventBus → 状态/输出 连接
# ---------------------------------------------------------------------------

def _on_bus_state(data):
    """bus.emit('state', {...}) → 更新 overlay + SSE。"""
    if isinstance(data, dict):
        _set_state(data.get("status", "ready"), data.get("text"))


def _on_bus_partial(text):
    """bus.emit('partial', text) → 更新 overlay 显示部分结果。"""
    if _wakeup_method == "vad":
        _set_state("active", text)
    else:
        _set_state("recording", text)


def _strip_end_keywords(text: str) -> str:
    """去除结尾的结束关键词（KWS 结束词会被 ASR 一起转录）。"""
    config = get_config()
    end_kws = config.get("wakeup", {}).get("end_keywords", [])
    if not end_kws:
        return text
    changed = True
    while changed:
        changed = False
        for kw in end_kws:
            for suffix in (kw, kw + "。", kw + "，", kw + " "):
                if text.endswith(suffix):
                    text = text[:-len(suffix)].rstrip("，。、 ")
                    changed = True
                    break
    return text


def _on_bus_result(text):
    """bus.emit('result', text) → LLM 处理 → 输出。"""
    if not text or not text.strip():
        return
    text = text.strip()
    if _wakeup_method == "vad":
        text = _strip_end_keywords(text)
        if not text:
            return
    logger.info("转录结果: %s", text[:80])

    config = get_config()
    mode = config.get("currentMode", "transcribe")

    if mode == "transcribe":
        _do_output(text, config)
        return

    # 翻译/润色模式
    _set_state("processing")
    if _loop is not None and _loop.is_running():
        future = asyncio.run_coroutine_threadsafe(_process_and_output(text, config, mode), _loop)
        try:
            future.result(timeout=120)
        except Exception as e:
            logger.error("LLM 处理失败，降级为直接输出: %s", e)
            _set_state("error", "LLM 处理失败")
            _do_output(text, config)
    else:
        _do_output(text, config)


def _on_bus_done(_):
    """bus.emit('done') → 恢复到当前模式的默认状态。"""
    global _recording
    _recording = False
    if _ui_state.get("status") == "error":
        def _delayed_restore():
            import time
            time.sleep(3)
            if _ui_state.get("status") == "error":
                _set_state("idle" if _wakeup_method == "vad" else "ready")
        threading.Thread(target=_delayed_restore, daemon=True).start()
    else:
        _set_state("idle" if _wakeup_method == "vad" else "ready")


def _on_bus_start(_):
    """bus.emit('start') → 标记录音中。"""
    global _recording
    _recording = True


async def _process_and_output(text: str, config: dict, mode: str) -> None:
    result = await process_text(text, config, mode=mode)
    output_text = result.get("processed_text", text)
    if result.get("fell_back_to_transcribe"):
        logger.warning("LLM 降级: %s", result.get("error", ""))
    _do_output(output_text, config)


def _do_output(text: str, config: dict) -> None:
    output_cfg = config.get("output", {})
    append_newline = output_cfg.get("append_newline", False)
    type_text(text, append_newline=append_newline, method="type")
    logger.info("已输出: %s", text[:50])


# ---------------------------------------------------------------------------
# 设备管理
# ---------------------------------------------------------------------------

def _resolve_device_id() -> str | None:
    from shokztype.web.services import device_monitor
    config = get_config()
    audio_cfg = config.get("audio", {})
    # 优先用 endpoint_id 匹配偏好设备（稳定标识）
    preferred = audio_cfg.get("preferred_device")
    if preferred is not None and str(preferred) != "":
        try:
            devices = device_monitor.list_devices()
            match = next((d for d in devices if d.get("endpoint_id") == str(preferred)), None)
            if match:
                return match["id"]
        except Exception:
            pass
    dev = audio_cfg.get("device")
    if dev is not None and str(dev) != "":
        return str(dev)
    try:
        default_idx = sd.default.device[0]
        return str(default_idx) if default_idx is not None else None
    except Exception:
        return None


def get_active_device_id() -> str | None:
    return _active_device_id


def get_preferred_endpoint_id() -> str | None:
    return _preferred_endpoint_id


def _handle_device_switch(new_device_id: str, current_devices: list) -> None:
    if not _device_switch_lock.acquire(blocking=False):
        logger.info("设备切换已在进行中，跳过")
        return
    try:
        global _active_device_id
        logger.info("切换到设备 #%s", new_device_id)
        update_config({"audio": {"device": new_device_id}})
        _active_device_id = new_device_id
        threading.Thread(
            target=_do_device_switch_restart, daemon=True, name="DeviceSwitchRestart",
        ).start()
    except Exception:
        _device_switch_lock.release()
        raise


def _on_portaudio_refresh() -> None:
    """PortAudio 重初始化后重建音频流。"""
    if _audio is not None:
        try:
            _audio.reopen_stream()
        except Exception as e:
            logger.warning("重建音频流失败: %s", e)


def _do_device_switch_restart() -> None:
    try:
        restart_pipeline()
    finally:
        _device_switch_lock.release()


# ---------------------------------------------------------------------------
# FunASR 模型复用
# ---------------------------------------------------------------------------

_cached_fun_server = None
_funasr_patch_installed = False


def ensure_funasr_loaded():
    """确保 FunASR 模型已加载。首次调用加载模型并安装复用 patch，后续调用直接返回。"""
    global _cached_fun_server, _funasr_patch_installed

    if _cached_fun_server is not None:
        return

    print("[FunASR] 正在加载本地 ASR 模型...")
    from shokztype.core.funasr_server import FunASRServer
    _cached_fun_server = FunASRServer()
    init_result = _cached_fun_server.initialize()
    if not init_result.get("success"):
        _cached_fun_server = None
        raise RuntimeError(f"FunASR 初始化失败: {init_result}")
    print("[FunASR] 模型加载完成")

    if not _funasr_patch_installed:
        _install_funasr_reuse_patch()
        _funasr_patch_installed = True


def _install_funasr_reuse_patch() -> None:
    import shokztype.core.funasr_server as funasr_mod
    import shokztype.core.transcribe as transcribe_mod
    import shokztype.core.vad_worker as vad_worker_mod

    cached = _cached_fun_server

    class ReusedFunASRServer:
        def __init__(self):
            self.__dict__.update(cached.__dict__)
        def initialize(self):
            return {"success": True, "message": "reused cached instance"}
        def cleanup(self):
            pass
        def __getattr__(self, name):
            return getattr(cached, name)

    funasr_mod.FunASRServer = ReusedFunASRServer
    transcribe_mod.FunASRServer = ReusedFunASRServer
    vad_worker_mod.FunASRServer = ReusedFunASRServer
    print("[FunASR] 复用 patch 已安装")


# ---------------------------------------------------------------------------
# 管线组装
# ---------------------------------------------------------------------------

_speaker_gate = None


def _assemble(config: dict) -> None:
    """根据配置组装唤醒模块 + 声纹门卫 + 转录模块。"""
    global _wakeup, _transcriber, _audio, _speaker_gate, _wakeup_method, _recording

    _recording = False
    wakeup_method = config.get("wakeup", {}).get("method", "hotkey")
    asr_backend = config.get("asr", {}).get("backend", "local")
    use_cloud = asr_backend in ("volcengine", "cloud")

    _wakeup_method = wakeup_method

    # 1. EventBus — 清除旧订阅，重新注册
    bus.clear()
    bus.on("state", _on_bus_state)
    bus.on("partial", _on_bus_partial)
    bus.on("result", _on_bus_result)
    bus.on("done", _on_bus_done)
    bus.on("start", _on_bus_start)
    bus.on("config_changed", _on_config_changed)

    # 2. AudioCapture（共享）
    audio_cfg = config.get("audio", {})
    _audio = AudioCapture(
        sample_rate=audio_cfg.get("sample_rate", 16000),
        block_ms=audio_cfg.get("block_ms", 20),
        device=audio_cfg.get("device"),
    )

    # 3. 唤醒模块（先创建，VAD 模式下转录模块需要它的 forward_queue）
    frame_source = None  # 帧来源队列：None = 直接读 audio.queue
    if wakeup_method == "vad":
        from shokztype.web.services.wakeup_vad_kws import VadKwsWakeup
        _wakeup = VadKwsWakeup(bus, _audio, config)
        frame_source = _wakeup.forward_queue
        print("[assemble] 唤醒模块: VAD+KWS")
    else:
        from shokztype.web.services.wakeup_hotkey import HotkeyWakeup
        combo = config.get("wakeup", {}).get("hotkey", {}).get("combo", "f2")
        _wakeup = HotkeyWakeup(bus, _audio, combo)
        print(f"[assemble] 唤醒模块: 热键 ({combo})")

    # 4. 声纹过滤（可选插入帧链路）
    vp_cfg = config.get("voiceprint", {})
    if vp_cfg.get("enabled") and vp_cfg.get("activeProfiles"):
        from shokztype.web.services.speaker_gate import SpeakerGate
        # 热键模式且无 VadKwsWakeup：SpeakerGate 直接读 audio.queue，需管 audio 生命周期
        gate_reads_audio_directly = (frame_source is None)
        _speaker_gate = SpeakerGate(
            bus,
            input_queue=frame_source or _audio.queue,
            audio=_audio if gate_reads_audio_directly else None,
        )
        transcriber_queue = _speaker_gate.output_queue
        print("[assemble] 声纹过滤: 已插入帧链路")
    else:
        _speaker_gate = None
        transcriber_queue = frame_source  # 直连
        print("[assemble] 声纹过滤: 未启用")

    # 5. 转录模块（从 transcriber_queue 读帧）
    if use_cloud:
        from shokztype.web.services.transcriber_stream import StreamTranscriber
        _transcriber = StreamTranscriber(bus, _audio, config, input_queue=transcriber_queue)
        print(f"[assemble] 转录模块: 流式云端 ({asr_backend})")
    else:
        from shokztype.web.services.transcriber_batch import BatchTranscriber
        _transcriber = BatchTranscriber(bus, _audio, config, input_queue=transcriber_queue)
        print("[assemble] 转录模块: 批量本地")

    # 6. 启动
    _wakeup.start()


def _teardown() -> None:
    """拆卸当前管线。"""
    global _wakeup, _transcriber, _audio, _speaker_gate

    if _speaker_gate is not None:
        try:
            _speaker_gate.cleanup()
        except Exception:
            pass
        _speaker_gate = None

    if _wakeup is not None:
        try:
            _wakeup.stop()
        except Exception:
            pass
        _wakeup = None

    if _transcriber is not None:
        try:
            _transcriber.cleanup()
        except Exception:
            pass
        _transcriber = None

    if _audio is not None:
        try:
            _audio.stop()
            _audio.cleanup()
        except Exception:
            pass
        _audio = None

    bus.clear()


# ---------------------------------------------------------------------------
# 生命周期 API
# ---------------------------------------------------------------------------

def init_worker() -> None:
    """初始化管线。"""
    global _ready, _init_error, _cached_fun_server

    _start_overlay()
    import time
    time.sleep(0.3)
    _set_state("loading")
    print("[init] overlay 已启动")

    config = get_config()
    asr_backend = config.get("asr", {}).get("backend", "local")
    use_cloud = asr_backend in ("volcengine", "cloud")

    # 本地 ASR：立即加载模型；云端 ASR：跳过（后续切换时懒加载）
    if not use_cloud:
        try:
            print("[init] 正在加载本地 ASR 模型...")
            ensure_funasr_loaded()
            print("[init] 本地 ASR 模型加载完成")
        except Exception as e:
            _init_error = str(e)
            print(f"[init] {_init_error}")
            return
    else:
        print(f"[init] 云端 ASR 模式 (backend={asr_backend})，本地模型按需加载")

    # 初始化声纹模块
    print("[init] 正在初始化声纹模块...")
    from shokztype.web.services.voiceprint_manager import init_speaker
    init_speaker(config)
    print("[init] 声纹模块已初始化")
    print("[init] 正在组装管线...")

    # 组装管线
    try:
        _assemble(config)
        _ready = True
        print("[init] 管线组装完成")
    except Exception as e:
        _init_error = str(e)
        print(f"[init] 管线组装失败: {e}")
        logger.error("管线组装失败: %s", e, exc_info=True)
        return

    _set_state("idle" if _wakeup_method == "vad" else "ready")
    print("[init] 全部完成，准备启动 Web 服务")


def start_pipeline(event_loop: asyncio.AbstractEventLoop) -> None:
    global _loop, _active_device_id, _preferred_endpoint_id
    _loop = event_loop

    config = get_config()
    _preferred_endpoint_id = config.get("audio", {}).get("preferred_device")
    if _preferred_endpoint_id is not None:
        _preferred_endpoint_id = str(_preferred_endpoint_id)

    _active_device_id = _resolve_device_id()

    from shokztype.web.services import device_monitor
    device_monitor.register_get_active_device(get_active_device_id)
    device_monitor.register_get_preferred_device(get_preferred_endpoint_id)
    device_monitor.register_on_device_switch(_handle_device_switch)
    device_monitor.register_on_portaudio_refresh(_on_portaudio_refresh)

    logger.info("事件循环已绑定，活跃设备: %s", _active_device_id)


def stop_pipeline() -> None:
    global _recording, _ready
    _recording = False
    _ready = False
    _teardown()
    _stop_overlay()
    logger.info("管线已停止")


def _on_config_changed(changes: dict) -> None:
    """配置变更 → 自动重组受影响的模块。

    只拆换变了的部分，bus 和 audio 尽量保留。
    """
    global _preferred_endpoint_id, _active_device_id

    audio_changes = changes.get("audio") or {}
    asr_changes = changes.get("asr") or {}
    wakeup_changes = changes.get("wakeup") or {}

    # 更新偏好设备（内存中的变量）
    if "preferred_device" in audio_changes:
        _preferred_endpoint_id = str(audio_changes["preferred_device"])

    # 判断哪些模块需要重组
    device_changed = "device" in audio_changes and str(audio_changes["device"]) != str(_active_device_id)
    asr_changed = "backend" in asr_changes
    wakeup_changed = "method" in wakeup_changes or "hotkey" in wakeup_changes or "end_keywords" in wakeup_changes or "keywords_file" in wakeup_changes
    voiceprint_changed = "voiceprint" in changes

    _set_state("saving")

    if not (device_changed or asr_changed or wakeup_changed or voiceprint_changed):
        # 只改了 LLM / prompt 等 → 不需要动管线
        logger.info("配置已更新，管线无需重组")
        _set_state("idle" if _wakeup_method == "vad" else "ready")
        return

    config = get_config()

    if voiceprint_changed:
        # 声纹开关变更 → 帧链路需要重组（插入/移除 SpeakerGate）
        logger.info("声纹配置变更 → 重组管线")
        threading.Thread(target=restart_pipeline, daemon=True, name="ConfigRestart").start()
    elif device_changed:
        _active_device_id = str(audio_changes["device"])
        logger.info("设备变更 → 重组管线")
        threading.Thread(target=restart_pipeline, daemon=True, name="ConfigRestart").start()
    elif asr_changed and not wakeup_changed:
        logger.info("ASR 后端变更 → 换转录模块")
        threading.Thread(target=_swap_transcriber, args=(config,), daemon=True, name="SwapASR").start()
    elif wakeup_changed and not asr_changed:
        logger.info("唤醒方式变更 → 换唤醒模块")
        threading.Thread(target=_swap_wakeup, args=(config,), daemon=True, name="SwapWakeup").start()
    else:
        logger.info("多项配置变更 → 重组管线")
        threading.Thread(target=restart_pipeline, daemon=True, name="ConfigRestart").start()


def _swap_transcriber(config: dict) -> None:
    """只替换转录模块，bus / audio / wakeup 不动。"""
    global _transcriber

    # 如果正在录音，先停掉
    if _recording and bus:
        bus.emit("stop")

    # 拆旧
    if _transcriber is not None:
        try:
            _transcriber.cleanup()
        except Exception:
            pass

    # 装新
    asr_backend = config.get("asr", {}).get("backend", "local")
    if asr_backend in ("volcengine", "cloud"):
        from shokztype.web.services.transcriber_stream import StreamTranscriber
        _transcriber = StreamTranscriber(bus, _audio, config)
        logger.info("转录模块已切换: 流式云端 (%s)", asr_backend)
    else:
        from shokztype.web.services.transcriber_batch import BatchTranscriber
        _transcriber = BatchTranscriber(bus, _audio, config)
        logger.info("转录模块已切换: 批量本地")

    _set_state("idle" if _wakeup_method == "vad" else "ready")


def _swap_wakeup(config: dict) -> None:
    """替换唤醒模块。模式切换涉及帧链路变更，必须全量重组。"""
    if _recording and bus:
        bus.emit("stop")
    restart_pipeline()


def restart_pipeline() -> dict:
    global _ready, _init_error, _active_device_id, _overlay_proc, _overlay_sock

    config = get_config()
    # 如果已经在 "saving" 状态（来自 config_changed），不覆盖
    if _ui_state.get("status") != "saving":
        _set_state("switching")

    saved_proc, saved_sock = _overlay_proc, _overlay_sock
    _overlay_proc, _overlay_sock = None, None
    stop_pipeline()
    _overlay_proc, _overlay_sock = saved_proc, saved_sock

    _ready = False
    _init_error = None

    try:
        _assemble(config)
        _ready = True
        _active_device_id = _resolve_device_id()
        _set_state("idle" if _wakeup_method == "vad" else "ready")
        print(f"[pipeline] 已切换到 {_wakeup_method} 模式")
        return {"success": True, "method": _wakeup_method}
    except Exception as e:
        _init_error = str(e)
        print(f"[pipeline] 切换失败: {e}")
        return {"success": False, "error": str(e)}


def is_recording() -> bool:
    return _recording


def pipeline_status() -> dict:
    return {**_ui_state, "active_device": _active_device_id}
