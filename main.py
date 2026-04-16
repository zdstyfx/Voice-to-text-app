"""Command-line entry for the speak-keyboard prototype."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time

import keyboard

from app import HotkeyManager, TranscriptionResult, TranscriptionWorker, load_config, type_text
from app.plugins.dataset_recorder import wrap_result_handler
from app.logging_config import setup_logging


logger = logging.getLogger(__name__)


def _beep(freq: int, duration_ms: int) -> None:
    """在后台线程播放提示音，避免阻塞主线程"""
    try:
        import winsound
        threading.Thread(
            target=winsound.Beep, args=(freq, duration_ms), daemon=True
        ).start()
    except Exception:
        pass


class RecordingOverlay:
    """录音状态置顶浮窗，录音时显示，停止时隐藏"""

    def __init__(self) -> None:
        self._show_event = threading.Event()
        self._hide_event = threading.Event()
        self._quit_event = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._gui_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3)

    def _gui_loop(self) -> None:
        import tkinter as tk

        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.88)
        root.configure(bg="#CC0000")

        label = tk.Label(
            root,
            text="  \u25cf  \u5f55\u97f3\u4e2d...  ",
            font=("Microsoft YaHei UI", 13, "bold"),
            fg="white",
            bg="#CC0000",
            padx=14,
            pady=6,
        )
        label.pack()

        # 放在屏幕右上角
        root.update_idletasks()
        x = root.winfo_screenwidth() - root.winfo_width() - 24
        root.geometry(f"+{x}+18")
        root.withdraw()
        self._ready.set()

        def _poll() -> None:
            if self._quit_event.is_set():
                root.destroy()
                return
            if self._show_event.is_set():
                self._show_event.clear()
                root.deiconify()
            if self._hide_event.is_set():
                self._hide_event.clear()
                root.withdraw()
            root.after(50, _poll)

        _poll()
        root.mainloop()

    def show(self) -> None:
        self._show_event.set()

    def hide(self) -> None:
        self._hide_event.set()

    def destroy(self) -> None:
        self._quit_event.set()


# 全局浮窗实例，延迟初始化
_overlay: RecordingOverlay | None = None


def _get_overlay() -> RecordingOverlay:
    global _overlay
    if _overlay is None:
        _overlay = RecordingOverlay()
    return _overlay


def _status_feedback(recording: bool) -> None:
    """录音状态反馈：提示音 + 置顶浮窗"""
    if recording:
        _beep(1000, 150)
        _get_overlay().show()
    else:
        _beep(600, 150)
        _get_overlay().hide()




def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Speak Keyboard prototype")
    parser.add_argument("--config", help="Path to config JSON")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single transcription cycle for debugging",
    )
    parser.add_argument(
        "--udp",
        metavar="HOST:PORT",
        help="ESP32 UDP audio source (e.g. 192.168.4.1:6000)",
    )
    parser.add_argument("--save-dataset", action="store_true", help="Persist audio/text pairs")
    parser.add_argument("--dataset-dir", default="dataset", help="Dataset output directory")
    parser.add_argument("--web", action="store_true", help="Launch Web UI instead of CLI")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)

    # 配置日志系统（统一配置）
    from app.config import ensure_logging_dir
    log_dir_abs = ensure_logging_dir(config)
    setup_logging(
        level=config["logging"].get("level", "INFO"),
        log_dir=log_dir_abs
    )

    if args.web:
        from app.web import start_web_ui
        start_web_ui(config)
        return

    # --udp 快捷参数：跳过菜单直接进转写
    if args.udp:
        audio_source = _create_udp_source(args.udp, config)
        _run_transcription_flow(args, config, audio_source=audio_source)
        return

    # 主菜单循环
    while True:
        print(f"\n{'=' * 50}")
        print("  === Vocotype ===\n")
        print("  选择功能:")
        print("  [1] 语音转写")
        print("  [2] ESP32 无线麦克风")
        print("  [3] 声纹注册/管理")
        choice = input("\n  输入 1/2/3: ").strip()

        if choice == "1":
            _run_transcription_flow(args, config)
            break
        elif choice == "2":
            _run_esp32_mic_mode()
            break
        elif choice == "3":
            from app.enrollment_ui import run_enrollment_menu
            run_enrollment_menu(config)
            # 返回主菜单
        else:
            print("  无效选择，请重新输入")


def _run_transcription_flow(args, config, audio_source=None) -> None:
    """语音转写流程（原 main() 的核心逻辑）"""
    output_cfg = config.get("output", {})
    output_method = output_cfg.get("method", "auto")
    append_newline = output_cfg.get("append_newline", False)

    # 交互式选择音频源
    if audio_source is None:
        print("\n  选择音频源:")
        print("  [1] 电脑麦克风（默认设备）")
        print("  [2] ESP32 UDP")
        print("  [3] 选择其他音频设备")
        src_choice = input("  输入 1/2/3: ").strip()
        if src_choice == "2":
            audio_cfg = config["audio"]
            esp32_host = audio_cfg.get("esp32_host", "192.168.4.1")
            esp32_port = audio_cfg.get("esp32_port", 6000)
            udp_addr = f"{esp32_host}:{esp32_port}"
            audio_source = _create_udp_source(udp_addr, config)
        elif src_choice == "3":
            device_index = _select_audio_device()
            if device_index is not None:
                from app.audio_capture import AudioCapture
                audio_source = AudioCapture(
                    sample_rate=config["audio"]["sample_rate"],
                    block_ms=config["audio"]["block_ms"],
                    device=device_index,
                )

    # 交互式选择 ASR 引擎
    _choose_asr_backend(config)

    # 交互式选择声纹识别
    speaker_mode, speaker_processor = _choose_speaker_mode(config)

    # 交互式选择录音模式
    print("\n  选择模式:")
    print("  [1] F2 热键模式（按 F2 开始/停止录音）")
    print("  [2] VAD 自动检测模式（持续监听）")
    print("  [3] VAD + KWS 语音助手模式（唤醒词激活）")
    mode_choice = input("  输入 1/2/3: ").strip()

    if mode_choice == "3":
        _run_kws_mode(args, config, output_method, append_newline, audio_source,
                      speaker_processor, speaker_mode)
    elif mode_choice == "2":
        _run_vad_mode(args, config, output_method, append_newline, audio_source,
                      speaker_processor, speaker_mode)
    else:
        _run_f2_mode(args, config, output_method, append_newline, audio_source)


def _run_esp32_mic_mode() -> None:
    """ESP32 无线麦克风模式"""
    from app.esp32_receiver import run_esp32_receiver

    print("\n  ESP32 无线麦克风模式")
    print("  是否保存录音文件?")
    print("  [1] 仅实时播放")
    print("  [2] 播放 + 保存 recording.raw")
    save_choice = input("  输入 1 或 2: ").strip()

    save_file = "recording.raw" if save_choice == "2" else None
    run_esp32_receiver(save_file=save_file)


def _choose_asr_backend(config) -> None:
    """交互选择 ASR 引擎（本地/云端），直接修改 config dict。"""
    print("\n  选择语音识别引擎:")
    print("  [1] 本地 FunASR（离线，需要下载模型）")
    print("  [2] 云端 DashScope（在线，需要 API Key）")
    asr_choice = input("  输入 1/2（默认 1）: ").strip()

    if asr_choice != "2":
        return

    # 检查 API key 是否可用
    import os
    api_key = config.get("cloud_asr", {}).get("api_key", "")
    if not api_key:
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("  ⚠ DashScope API Key 未配置！")
        print("  请在 config.json 设置 cloud_asr.api_key 或设置环境变量 DASHSCOPE_API_KEY")
        print("  → 回退到本地 FunASR")
        return

    config["asr"]["backend"] = "cloud"
    logger.info("ASR 引擎: 云端 DashScope (模型: %s)", config.get("cloud_asr", {}).get("model", "paraformer-realtime-v2"))


def _choose_speaker_mode(config):
    """交互选择声纹识别模式，返回 (mode_str, processor_or_None)"""
    print("\n  声纹识别:")
    print("  [1] 关闭（不使用声纹）")
    print("  [2] 识别模式（标注说话人，已注册标名字，未注册自动区分）")
    print("  [3] 过滤模式（只转录指定人）")
    spk_choice = input("  输入 1/2/3: ").strip()

    if spk_choice not in ("2", "3"):
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
        logger.info("声纹识别模式已启用（含自动分离）")
        return "identify", processor

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


def _create_udp_source(udp_addr: str, config):
    from app.udp_audio_source import UDPAudioSource
    parts = udp_addr.rsplit(":", 1)
    esp32_host = parts[0]
    esp32_port = int(parts[1]) if len(parts) > 1 else 6000
    source = UDPAudioSource(
        esp32_host=esp32_host,
        esp32_port=esp32_port,
        listen_port=config["audio"].get("listen_port", 6000),
        sample_rate=config["audio"]["sample_rate"],
        block_ms=config["audio"]["block_ms"],
    )
    logger.info("UDP 音频源: ESP32 %s:%d", esp32_host, esp32_port)
    return source


def _select_audio_device() -> int | None:
    """List all system input devices and let user pick one. Returns device index or None."""
    import sounddevice as sd

    devices = sd.query_devices()
    input_devices = []
    for idx, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            input_devices.append((idx, dev["name"]))

    if not input_devices:
        print("  未找到可用的输入设备")
        return None

    print("\n  可用输入设备:")
    for i, (idx, name) in enumerate(input_devices, 1):
        # Mark default device
        default_in = sd.default.device[0]
        marker = " (默认)" if idx == default_in else ""
        print(f"  [{i}] {name}{marker}")

    sel = input("\n  输入序号: ").strip()
    if not sel.isdigit() or not (1 <= int(sel) <= len(input_devices)):
        print("  无效选择，使用默认设备")
        return None

    chosen_idx, chosen_name = input_devices[int(sel) - 1]
    print(f"  已选择: {chosen_name}")
    return chosen_idx


def _run_f2_mode(args, config, output_method, append_newline, audio_source) -> None:
    worker = TranscriptionWorker(
        config_path=args.config,
        on_result=None,
        audio_source=audio_source,
    )
    worker.on_result = _make_result_handler(output_method, append_newline, worker)
    if args.save_dataset:
        worker.on_result = wrap_result_handler(worker.on_result, worker, args.dataset_dir)

    hotkeys = HotkeyManager()
    toggle_combo = config["hotkeys"].get("toggle", "f2")

    try:
        keyboard.on_release_key(toggle_combo, lambda _: _toggle(worker), suppress=False)
        mode_hint = "UDP" if audio_source is not None else "麦克风"
        logger.info("Speak Keyboard 启动完成（%s模式），按 %s 开始/停止录音，按 Ctrl+C 退出", mode_hint, toggle_combo)
        try:
            print(f"\n{'='*50}")
            print(f"  Vocotype 就绪 ({mode_hint}模式)")
            print(f"  按 {toggle_combo.upper()} 开始/停止录音")
            print(f"  按 Ctrl+C 退出")
            print(f"{'='*50}\n")
        except Exception:
            pass
        if args.once:
            _toggle(worker)
            input("按 Enter 停止并退出...")
            _toggle(worker)
        else:
            keyboard.wait()
    except KeyboardInterrupt:
        logger.info("用户中断，正在退出...")
    except Exception as exc:
        logger.error("意外异常导致退出: %s", exc, exc_info=True)
    finally:
        try:
            worker.stop()
        except Exception as exc:
            logger.debug("停止 worker 时出错: %s", exc)
        try:
            worker.cleanup()
        except Exception as exc:
            logger.debug("清理 worker 时出错: %s", exc)
        try:
            if worker.fun_server:
                worker.fun_server.cleanup()
        except Exception as exc:
            logger.debug("清理 FunASR 服务器时出错: %s", exc)
        try:
            hotkeys.cleanup()
        except Exception as exc:
            logger.debug("清理热键时出错: %s", exc)
        if _overlay is not None:
            try:
                _overlay.destroy()
            except Exception:
                pass
        logger.info("所有资源已清理，正常退出")
        sys.exit(0)


def _run_vad_mode(args, config, output_method, append_newline, audio_source,
                  speaker_processor=None, speaker_mode="off") -> None:
    from app.vad_worker import VadTranscriptionWorker

    speaker_cluster = None
    if speaker_mode in ("identify", "diarize"):
        from app.speaker_cluster import SpeakerCluster
        threshold = config.get("speaker", {}).get("threshold", 0.45)
        speaker_cluster = SpeakerCluster(threshold=threshold)

    # 云端模式下使用流式回调
    asr_backend = config.get("asr", {}).get("backend", "local")
    on_partial, on_sentence = (None, None)
    if asr_backend == "cloud":
        on_partial, on_sentence = _make_streaming_callbacks(output_method, append_newline)

    worker = VadTranscriptionWorker(
        config_path=args.config,
        on_result=None,
        audio_source=audio_source,
        speaker_processor=speaker_processor,
        speaker_mode=speaker_mode,
        speaker_cluster=speaker_cluster,
        on_partial=on_partial,
        on_sentence=on_sentence,
    )
    worker.on_result = _make_result_handler(output_method, append_newline, worker)
    if args.save_dataset:
        worker.on_result = wrap_result_handler(worker.on_result, worker, args.dataset_dir)

    try:
        worker.start()
        mode_hint = "UDP" if audio_source is not None else "麦克风"
        streaming_hint = "流式" if asr_backend == "cloud" else ""
        logger.info("VAD 自动检测模式启动（%s%s）", streaming_hint, mode_hint)
        try:
            print(f"\n{'='*50}")
            if asr_backend == "cloud":
                print(f"  Vocotype 就绪 (云端流式模式, {mode_hint})")
                print(f"  持续监听中，边说边出字")
            else:
                print(f"  Vocotype 就绪 (VAD 自动检测模式, {mode_hint})")
                print(f"  持续监听中，说话即自动转录")
            print(f"  按 Ctrl+C 退出")
            print(f"{'='*50}\n")
        except Exception:
            pass
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("用户中断，正在退出...")
    except Exception as exc:
        logger.error("意外异常导致退出: %s", exc, exc_info=True)
    finally:
        try:
            worker.stop()
        except Exception as exc:
            logger.debug("停止 VAD worker 时出错: %s", exc)
        try:
            worker.cleanup()
        except Exception as exc:
            logger.debug("清理 VAD worker 时出错: %s", exc)
        try:
            if worker.fun_server:
                worker.fun_server.cleanup()
        except Exception as exc:
            logger.debug("清理 FunASR 服务器时出错: %s", exc)
        logger.info("所有资源已清理，正常退出")
        sys.exit(0)


def _run_kws_mode(args, config, output_method, append_newline, audio_source,
                  speaker_processor=None, speaker_mode="off") -> None:
    """KWS 语音助手模式"""
    from app.vad_worker import VadTranscriptionWorker

    config["kws"]["enabled"] = True

    speaker_cluster = None
    if speaker_mode in ("identify", "diarize"):
        from app.speaker_cluster import SpeakerCluster
        threshold = config.get("speaker", {}).get("threshold", 0.45)
        speaker_cluster = SpeakerCluster(threshold=threshold)

    # 云端模式下使用流式回调
    asr_backend = config.get("asr", {}).get("backend", "local")
    on_partial, on_sentence = (None, None)
    if asr_backend == "cloud":
        on_partial, on_sentence = _make_streaming_callbacks(output_method, append_newline)

    worker = VadTranscriptionWorker(
        config_path=args.config,
        on_result=None,
        audio_source=audio_source,
        speaker_processor=speaker_processor,
        speaker_mode=speaker_mode,
        speaker_cluster=speaker_cluster,
        kws_enabled=True,
        on_partial=on_partial,
        on_sentence=on_sentence,
    )
    worker.on_result = _make_result_handler(output_method, append_newline, worker)
    if args.save_dataset:
        worker.on_result = wrap_result_handler(worker.on_result, worker, args.dataset_dir)

    try:
        worker.start()
        mode_hint = "UDP" if audio_source is not None else "麦克风"
        logger.info("KWS 语音助手模式启动（%s）", mode_hint)
        print(f"\n{'='*50}")
        print(f"  Vocotype 就绪 (KWS 语音助手模式, {mode_hint})")
        print(f"  说唤醒词激活，超时自动回到监听态")
        print(f"  按 Ctrl+C 退出")
        print(f"{'='*50}\n")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("用户中断，正在退出...")
    except Exception as exc:
        logger.error("意外异常导致退出: %s", exc, exc_info=True)
    finally:
        try:
            worker.stop()
        except Exception as exc:
            logger.debug("停止 KWS worker 时出错: %s", exc)
        try:
            worker.cleanup()
        except Exception as exc:
            logger.debug("清理 KWS worker 时出错: %s", exc)
        try:
            if worker.fun_server:
                worker.fun_server.cleanup()
        except Exception as exc:
            logger.debug("清理 FunASR 服务器时出错: %s", exc)
        logger.info("所有资源已清理，正常退出")
        sys.exit(0)


# ------------------------------------------------------------------
# 流式 ASR 终端实时显示
# ------------------------------------------------------------------

def _make_streaming_callbacks(output_method: str, append_newline: bool):
    """为云端流式 ASR 创建 on_partial / on_sentence 回调。

    中间结果用 \\r 覆盖当前行，最终结果换行确认。
    最终结果同时通过 type_text() 输出到焦点窗口。
    """
    last_partial_len = [0]  # mutable container for nonlocal access

    def on_partial(text: str) -> None:
        # 获取终端宽度，截断过长的中间结果
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 80
        display = text[:cols - 1]
        # 用空格覆盖上一次残留字符
        padding = max(0, last_partial_len[0] - len(display))
        sys.stdout.write(f"\r{display}{' ' * padding}")
        sys.stdout.flush()
        last_partial_len[0] = len(display)

    def on_sentence(text: str) -> None:
        # 覆盖中间结果行并换行确认
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 80
        padding = max(0, last_partial_len[0] - len(text))
        sys.stdout.write(f"\r{text}{' ' * padding}\n")
        sys.stdout.flush()
        last_partial_len[0] = 0

        # 同时输出到焦点窗口
        if text.strip():
            type_text(text, append_newline=append_newline, method=output_method)

    return on_partial, on_sentence


_PUNC_CHARS = set("，。！？、；：""''（）【】《》—…· ,.!?;:")


def _remove_overlap(prev: str, curr: str, max_overlap: int = 25) -> str:
    """Remove overlapping prefix of *curr* that duplicates suffix of *prev*.

    Comparison ignores punctuation so that the same words with different
    punctuation (e.g. "功能。" vs "功能，") are still detected as overlap.
    """
    if not prev or not curr:
        return curr

    prev_clean = "".join(c for c in prev if c not in _PUNC_CHARS)
    curr_clean = "".join(c for c in curr if c not in _PUNC_CHARS)

    if not prev_clean or not curr_clean:
        return curr

    max_check = min(len(prev_clean), len(curr_clean), max_overlap)
    best = 0
    for length in range(max_check, 1, -1):
        if prev_clean[-length:] == curr_clean[:length]:
            best = length
            break

    if best < 2:
        return curr

    # Map *best* clean-char count to an index in the original *curr* string
    clean_seen = 0
    for i, ch in enumerate(curr):
        if ch not in _PUNC_CHARS:
            clean_seen += 1
        if clean_seen >= best:
            tail = curr[i + 1:]
            # Strip leading punctuation left over from the removed overlap
            while tail and tail[0] in _PUNC_CHARS:
                tail = tail[1:]
            return tail

    return curr


def _make_result_handler(output_method: str, append_newline: bool, worker):
    prev_text = ""

    def _handle_result(result: TranscriptionResult) -> None:
        nonlocal prev_text

        if result.error:
            logger.error("转写失败: %s", result.error)
            return

        # 获取转录统计信息
        stats = worker.transcription_stats

        # 去除与上一段重叠的前缀
        deduped = _remove_overlap(prev_text, result.text)
        prev_text = result.text

        # 构建输出文本（识别模式加说话人前缀）
        output_text = deduped
        if result.speaker:
            output_text = f"[{result.speaker}] {deduped}"
            logger.info(
                "转写成功: [%s](%.2f) %s (推理 %.2fs) [已完成 %d/%d，队列剩余 %d]",
                result.speaker,
                result.speaker_confidence or 0.0,
                result.text,
                result.inference_latency,
                stats["completed"],
                stats["submitted"],
                stats["pending"],
            )
        else:
            logger.info(
                "转写成功: %s (推理 %.2fs) [已完成 %d/%d，队列剩余 %d]",
                result.text,
                result.inference_latency,
                stats["completed"],
                stats["submitted"],
                stats["pending"],
            )

        if deduped != result.text:
            logger.debug("去重: '%s' → '%s'", result.text, deduped)

        type_text(
            output_text,
            append_newline=append_newline,
            method=output_method,
        )

    return _handle_result


def _toggle(worker: TranscriptionWorker) -> None:
    """F2 松开时触发：切换录音状态"""
    if worker.is_running:
        worker.stop()
        _status_feedback(False)
        stats = worker.transcription_stats
        if stats["pending"] > 0:
            logger.info("录音已停止并提交转录，队列中还有 %d 个任务等待处理", stats["pending"])
    else:
        stats = worker.transcription_stats
        if stats["pending"] > 0:
            logger.info("开始录音（后台还有 %d 个转录任务正在处理）", stats["pending"])
        worker.start()
        _status_feedback(True)


if __name__ == "__main__":
    main()

