"""Command-line entry for the speak-keyboard prototype."""

from __future__ import annotations

import argparse
import logging
import sys
import threading

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

    output_cfg = config.get("output", {})
    output_method = output_cfg.get("method", "auto")
    append_newline = output_cfg.get("append_newline", False)

    # 解析 UDP 参数
    audio_source = None
    if args.udp:
        from app.udp_audio_source import UDPAudioSource
        parts = args.udp.rsplit(":", 1)
        esp32_host = parts[0]
        esp32_port = int(parts[1]) if len(parts) > 1 else 6000
        audio_source = UDPAudioSource(
            esp32_host=esp32_host,
            esp32_port=esp32_port,
            listen_port=config["audio"].get("listen_port", 6000),
            sample_rate=config["audio"]["sample_rate"],
            block_ms=config["audio"]["block_ms"],
        )
        logger.info("UDP 模式: ESP32 %s:%d", esp32_host, esp32_port)

    # 先创建worker（没有回调）
    worker = TranscriptionWorker(
        config_path=args.config,
        on_result=None,  # 稍后设置
        audio_source=audio_source,
    )
    
    # 创建result handler（需要worker引用）
    worker.on_result = _make_result_handler(output_method, append_newline, worker)
    if args.save_dataset:
        worker.on_result = wrap_result_handler(worker.on_result, worker, args.dataset_dir)
    
    hotkeys = HotkeyManager()

    toggle_combo = config["hotkeys"].get("toggle", "f2")

    try:
        # 仅在松开 F2 时触发切换（避免按住时键盘重复导致多次触发）
        keyboard.on_release_key(toggle_combo, lambda _: _toggle(worker), suppress=False)
        mode_hint = "UDP" if args.udp else "麦克风"
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
        # 清理所有资源
        try:
            worker.stop()
        except Exception as exc:
            logger.debug("停止 worker 时出错: %s", exc)
        
        try:
            worker.cleanup()
        except Exception as exc:
            logger.debug("清理 worker 时出错: %s", exc)
        
        try:
            # 显式清理 FunASR 模型资源
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
        import sys
        sys.exit(0)


def _make_result_handler(output_method: str, append_newline: bool, worker: TranscriptionWorker):
    def _handle_result(result: TranscriptionResult) -> None:
        if result.error:
            logger.error("转写失败: %s", result.error)
            return

        # 获取转录统计信息
        stats = worker.transcription_stats
        
        logger.info(
            "转写成功: %s (推理 %.2fs) [已完成 %d/%d，队列剩余 %d]",
            result.text,
            result.inference_latency,
            stats["completed"],
            stats["submitted"],
            stats["pending"],
        )
        type_text(
            result.text,
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

