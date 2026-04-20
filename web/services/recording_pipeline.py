"""全链路管线：支持热键唤醒和 VAD+KWS 唤醒两种模式。

热键模式：F2 toggle 开始/停止录音 → ASR → LLM → 输出
VAD+KWS 模式：持续监听 → 唤醒词激活 → VAD 检测语音 → ASR → LLM → 输出
"""

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import threading

import keyboard

from app import TranscriptionResult, TranscriptionWorker, type_text
from web.web_config import get_config
from web.services.text_pipeline import process_text
from web.services.voiceprint_manager import get_speaker_processor

logger = logging.getLogger(__name__)

# 当前 worker（TranscriptionWorker 或 VadTranscriptionWorker）
_worker = None
_loop: asyncio.AbstractEventLoop | None = None
_recording = False
_ready = False
_init_error: str | None = None
_wakeup_method: str = "hotkey"  # "hotkey" | "vad"
_first_active_result = False  # ACTIVE 后的第一条结果需要过滤唤醒词

WAKE_WORDS = ["你好小韶", "你好小助手"]

# ---------------------------------------------------------------------------
# 系统浮窗（独立进程，UDP 通信）
# ---------------------------------------------------------------------------
_OVERLAY_PORT = 9123
_overlay_proc: subprocess.Popen | None = None
_overlay_sock: socket.socket | None = None


def _start_overlay():
    """启动浮窗独立进程。"""
    global _overlay_proc, _overlay_sock
    try:
        script = os.path.join(os.path.dirname(__file__), "overlay_process.py")
        _overlay_proc = subprocess.Popen(
            [sys.executable, script, "--port", str(_OVERLAY_PORT)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _overlay_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        logger.info("浮窗进程已启动 (PID=%d)", _overlay_proc.pid)
    except Exception as e:
        logger.warning("浮窗启动失败: %s", e)


def _stop_overlay():
    """关闭浮窗进程。"""
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


def _send_overlay(status: str, text: str | None = None):
    """向浮窗发送状态更新。"""
    if _overlay_sock is None:
        return
    try:
        msg = json.dumps({"status": status, "text": text}, ensure_ascii=False)
        _overlay_sock.sendto(msg.encode("utf-8"), ("127.0.0.1", _OVERLAY_PORT))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 提示音
# ---------------------------------------------------------------------------

def _beep(freq: int, duration_ms: int) -> None:
    try:
        import winsound
        threading.Thread(target=winsound.Beep, args=(freq, duration_ms), daemon=True).start()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ASR 结果回调 → LLM → 输出
# ---------------------------------------------------------------------------

def _on_result(result: TranscriptionResult) -> None:
    if result.error:
        logger.error("转写失败: %s", result.error)
        return

    text = result.text
    if not text or not text.strip():
        return

    # 过滤第一条结果中的唤醒词（ACTIVE 刚开始时的残留音频）
    global _first_active_result
    if _wakeup_method == "vad":
        if _first_active_result:
            _first_active_result = False
            for ww in WAKE_WORDS:
                text = text.replace(ww, "")
            text = text.strip().lstrip("，。、！？,.")
            if not text:
                return

    logger.info("ASR 完成: %s (%.2fs)", text, result.inference_latency)

    config = get_config()
    mode = config.get("currentMode", "transcribe")

    if mode == "transcribe":
        _do_output(text, config)
        _send_overlay_current_state()
        return

    # 翻译/润色模式
    _send_overlay("processing")
    if _loop is not None and _loop.is_running():
        future = asyncio.run_coroutine_threadsafe(_process_and_output(text, config, mode), _loop)
        try:
            future.result(timeout=120)
        except Exception as e:
            logger.error("LLM 处理失败，降级为直接输出: %s", e)
            _do_output(text, config)
    else:
        _do_output(text, config)
    _send_overlay_current_state()


async def _process_and_output(text: str, config: dict, mode: str) -> None:
    result = await process_text(text, config, mode=mode)
    output_text = result.get("processed_text", text)
    if result.get("fell_back_to_transcribe"):
        logger.warning("LLM 降级: %s", result.get("error", ""))
    _do_output(output_text, config)


def _check_speaker(samples) -> bool:
    """声纹前置检查：在 ASR 之前判断是否是目标说话人。返回 True 表示通过。"""
    config = get_config()
    vp_cfg = config.get("voiceprint", {})
    if not vp_cfg.get("enabled"):
        return True

    active = vp_cfg.get("activeProfiles", [])
    if not active:
        return True

    sp = get_speaker_processor()
    if not sp:
        return True

    try:
        import numpy as np
        sp_result = sp.identify(samples)
        speaker = sp_result.speaker_id if sp_result.is_known else None
        logger.info("声纹前置检查: %s (%.2f)", speaker or "unknown", sp_result.confidence)
        if speaker and speaker in active:
            return True
        logger.info("声纹过滤: '%s' 不在激活列表 %s，跳过 ASR", speaker or "unknown", active)
        return False
    except Exception as e:
        logger.warning("声纹检查失败，放行: %s", e)
        return True


def _patch_worker_speaker_check(worker):
    """Patch worker 的 _transcribe_once，在 ASR 前插入声纹检查。"""
    orig_transcribe_once = worker._transcribe_once

    def _patched_transcribe_once(samples):
        if not _check_speaker(samples):
            _send_overlay_current_state()
            return
        orig_transcribe_once(samples)

    worker._transcribe_once = _patched_transcribe_once


def _send_overlay_current_state():
    """根据当前管线状态发送浮窗更新。"""
    if _wakeup_method == "vad" and _worker:
        kws = getattr(_worker, "_kws_state", "idle")
        _send_overlay("active" if kws == "active" else "idle")
    elif _recording:
        _send_overlay("recording")
    else:
        _send_overlay("ready")


def _do_output(text: str, config: dict) -> None:
    output_cfg = config.get("output", {})
    append_newline = output_cfg.get("append_newline", False)
    type_text(text, append_newline=append_newline, method="type")
    logger.info("已输出: %s", text[:50])


# ---------------------------------------------------------------------------
# 热键模式
# ---------------------------------------------------------------------------

def _toggle() -> None:
    """F2 热键回调：切换录音状态。"""
    global _recording
    if _worker is None:
        logger.warning("管线未就绪，忽略热键")
        return

    if _worker.is_running:
        _worker.stop()
        _recording = False
        _beep(600, 150)
        _send_overlay("processing")
        stats = _worker.transcription_stats
        logger.info("录音停止，队列中 %d 个任务", stats["pending"])
    else:
        _worker.start()
        _recording = True
        _beep(1000, 150)
        _send_overlay("recording")
        logger.info("开始录音")


def _register_hotkey() -> None:
    """在独立线程中注册热键（keyboard 库需要自己的消息泵）。"""
    config = get_config()
    wakeup = config.get("wakeup", {})
    combo = wakeup.get("hotkey", {}).get("combo", "f2")
    keyboard.on_release_key(combo, lambda _: _toggle(), suppress=False)
    logger.info("热键 %s 已注册", combo.upper())
    keyboard.wait()


# ---------------------------------------------------------------------------
# VAD + KWS 模式
# ---------------------------------------------------------------------------

def _start_vad_kws_worker() -> None:
    """启动 VAD+KWS 连续监听 worker。"""
    global _worker, _recording

    from app.vad_worker import VadTranscriptionWorker

    config = get_config()

    # 启用 KWS
    config["kws"]["enabled"] = True

    # 声纹识别
    sp = get_speaker_processor()
    vp_cfg = config.get("voiceprint", {})
    speaker_mode = "filter" if (vp_cfg.get("enabled") and sp) else "off"
    if speaker_mode == "filter" and sp:
        whitelist = vp_cfg.get("activeProfiles", [])
        sp._whitelist = set(whitelist) if whitelist else set()
        logger.info("声纹过滤已启用，白名单: %s", whitelist)

    speaker_cluster = None
    if speaker_mode != "off" and sp:
        from app.speaker_cluster import SpeakerCluster
        threshold = config.get("speaker", {}).get("threshold", 0.45)
        speaker_cluster = SpeakerCluster(threshold=threshold)

    _worker = VadTranscriptionWorker(
        config_path=None,
        on_result=_on_result,
        kws_enabled=True,
        speaker_processor=sp if speaker_mode != "off" else None,
        speaker_mode=speaker_mode,
        speaker_cluster=speaker_cluster,
    )

    # 用配置中的结束关键词替换 CommandDispatcher 默认的 exit_active
    end_keywords = config.get("wakeup", {}).get("end_keywords", ["退出", "取消", "再见"])
    if _worker._command_dispatcher:
        for cmd in _worker._command_dispatcher._commands:
            if cmd.name == "exit_active":
                cmd.keywords = end_keywords
                logger.info("结束关键词已更新: %s", end_keywords)
                break

    # 拦截 IDLE→ACTIVE 切换，标记下一条结果需过滤唤醒词
    _orig_to_active = _worker._kws_to_active
    def _patched_to_active():
        global _first_active_result
        _first_active_result = True
        _send_overlay("active")
        _orig_to_active()
    _worker._kws_to_active = _patched_to_active

    _orig_to_idle = _worker._kws_to_idle
    def _patched_to_idle():
        _send_overlay("idle")
        _orig_to_idle()
    _worker._kws_to_idle = _patched_to_idle

    _worker.start()
    _recording = True
    logger.info("VAD+KWS 连续监听模式已启动（说唤醒词激活）")


# ---------------------------------------------------------------------------
# 初始化 + 生命周期
# ---------------------------------------------------------------------------

def init_worker() -> None:
    """初始化管线：先加载 FunASR（一次性），然后根据配置启动对应模式。"""
    global _worker, _ready, _init_error, _wakeup_method, _cached_fun_server

    # 0. 启动浮窗
    _start_overlay()
    import time
    time.sleep(0.3)
    _send_overlay("loading")

    # 1. 一次性加载 FunASR 模型（主线程，后续永久复用）
    print("[init] 正在加载 ASR 模型（仅此一次）...")
    from app.funasr_server import FunASRServer
    _cached_fun_server = FunASRServer()
    init_result = _cached_fun_server.initialize()
    if not init_result.get("success"):
        _init_error = f"FunASR 初始化失败: {init_result}"
        print(f"[init] {_init_error}")
        return
    print("[init] ASR 模型加载完成，后续切换模式将复用此实例")

    # 2. 永久 patch，让所有 Worker 复用已加载的 FunASR
    _install_funasr_reuse_patch()

    # 3. 初始化声纹模块
    print("[init] 初始化声纹模块...")
    from web.services.voiceprint_manager import init_speaker
    config = get_config()
    init_speaker(config)
    sp = get_speaker_processor()
    if sp:
        print("[init] 声纹模块就绪")
    else:
        print("[init] 声纹模块未启用（模型未加载）")

    # 4. 根据配置启动对应模式
    config = get_config()
    _wakeup_method = config.get("wakeup", {}).get("method", "hotkey")

    if _wakeup_method == "vad":
        try:
            _start_vad_kws_worker()
            _ready = True
            _beep(800, 100)
            print("[init] VAD+KWS 模式就绪")
        except Exception as e:
            _init_error = str(e)
            print(f"[init] VAD+KWS 初始化失败: {e}")
            logger.error("VAD+KWS 初始化失败: %s", e, exc_info=True)
    else:
        try:
            _worker = TranscriptionWorker(config_path=None, on_result=_on_result)
            _ready = True
            _patch_worker_speaker_check(_worker)
            print("[init] ASR Worker 创建完成（含声纹前置检查）")
        except Exception as e:
            _init_error = str(e)
            print(f"[init] Worker 创建失败: {e}")
            return

        print("[init] 启动热键线程...")
        hotkey_thread = threading.Thread(target=_register_hotkey, daemon=True)
        hotkey_thread.start()
        import time
        time.sleep(0.5)
        print("[init] 热键线程已启动")
        _beep(800, 100)

    _send_overlay_current_state()
    print("[init] 全部完成，准备启动 Web 服务")


def _install_funasr_reuse_patch() -> None:
    """永久替换 FunASRServer，让所有新建的 Worker 复用已加载的模型。"""
    import app.funasr_server as funasr_mod
    import app.transcribe as transcribe_mod
    import app.vad_worker as vad_worker_mod

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
    print("[init] FunASR 复用 patch 已安装")


def start_pipeline(event_loop: asyncio.AbstractEventLoop) -> None:
    """设置事件循环引用。"""
    global _loop
    _loop = event_loop
    logger.info("事件循环已绑定，管线模式: %s", _wakeup_method)


def stop_pipeline() -> None:
    global _worker, _recording, _ready
    _recording = False
    _ready = False

    try:
        keyboard.unhook_all()
    except Exception:
        pass

    if _worker is not None:
        try:
            if hasattr(_worker, '_running'):
                _worker.stop()
        except Exception:
            pass
        try:
            if hasattr(_worker, '_running'):
                _worker.cleanup()
        except Exception:
            pass
        try:
            if hasattr(_worker, 'fun_server') and _worker.fun_server:
                _worker.fun_server.cleanup()
        except Exception:
            pass
        _worker = None

    _stop_overlay()
    logger.info("全链路管线已停止")


def is_recording() -> bool:
    return _recording


_cached_fun_server = None


def restart_pipeline() -> dict:
    """重启管线。FunASR 已永久 patch 为复用模式，切换很快。"""
    global _worker, _ready, _init_error, _recording, _wakeup_method, _first_active_result, _overlay_proc, _overlay_sock

    config = get_config()
    new_method = config.get("wakeup", {}).get("method", "hotkey")

    # 重启时不关闭浮窗，只更新状态
    _send_overlay("switching")

    # 保存浮窗引用，stop_pipeline 不要关闭它
    saved_proc, saved_sock = _overlay_proc, _overlay_sock
    _overlay_proc, _overlay_sock = None, None
    stop_pipeline()
    _overlay_proc, _overlay_sock = saved_proc, saved_sock

    _ready = False
    _init_error = None
    _recording = False
    _first_active_result = False

    try:
        if new_method == "vad":
            _start_vad_kws_worker()
            _wakeup_method = "vad"
            _ready = True
            _beep(800, 100)
            print("[pipeline] 已切换到 VAD+KWS 模式")
        else:
            _worker = TranscriptionWorker(config_path=None, on_result=_on_result)
            _patch_worker_speaker_check(_worker)
            _wakeup_method = "hotkey"
            _ready = True

            hotkey_thread = threading.Thread(target=_register_hotkey, daemon=True)
            hotkey_thread.start()
            import time
            time.sleep(0.3)

            _beep(800, 100)
            print("[pipeline] 已切换到热键模式")

        _send_overlay_current_state()
        return {"success": True, "method": new_method}
    except Exception as e:
        _init_error = str(e)
        print(f"[pipeline] 切换失败: {e}")
        return {"success": False, "error": str(e)}


def pipeline_status() -> dict:
    kws_state = None
    if _wakeup_method == "vad" and _worker is not None:
        kws_state = getattr(_worker, "_kws_state", None)
    return {
        "ready": _ready,
        "recording": _recording,
        "wakeup_method": _wakeup_method,
        "kws_state": kws_state,
        "error": _init_error,
    }
