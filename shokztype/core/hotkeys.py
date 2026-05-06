"""Global hotkey management using pynput (cross-platform).

On macOS frozen apps (PyInstaller), pynput's CGEventTap silently fails to
receive events in the pywebview process. The packaged app therefore prefers a
small Swift CGEventTap helper process and receives hotkey notifications over
UDP.
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from pynput import keyboard

logger = logging.getLogger(__name__)

IS_MACOS_FROZEN = sys.platform == "darwin" and getattr(sys, "frozen", False)

MODIFIER_KEYS = frozenset({
    keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
    keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r,
    keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r,
    keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r,
})


def _normalize_combo(combo: str) -> str:
    """Normalize hotkey combo string to pynput format like '<ctrl>+<alt>+f2'."""
    parts = [p.strip().lower() for p in combo.split("+")]
    result = []
    for p in parts:
        if p in ("ctrl", "control"):
            result.append("<ctrl>")
        elif p in ("alt",):
            result.append("<alt>")
        elif p in ("shift",):
            result.append("<shift>")
        elif p in ("cmd", "command", "super", "win"):
            result.append("<cmd>")
        elif len(p) > 1:
            result.append(f"<{p}>")
        else:
            result.append(p)
    return "+".join(result)


def _runtime_log_dir(
    app_executable: str | Path | None = None,
    home: str | Path | None = None,
) -> Path:
    """Return the writable runtime log directory.

    Args:
        app_executable: Frozen application executable path. Accepted for tests
            and future path decisions; logs intentionally never live beside it.
        home: User home directory override for tests.

    Returns:
        Directory path for ShokzType runtime logs.
    """
    _ = app_executable
    base_home = Path(home).expanduser() if home is not None else Path.home()
    return base_home / "Library" / "Logs" / "ShokzType"


def _helper_command(
    app_dir: str | Path,
    executable: str | Path,
    port: int,
    combo: str,
) -> list[str]:
    """Build the hotkey helper launch command.

    Args:
        app_dir: Directory containing packaged executables.
        executable: Current Python/PyInstaller executable path.
        port: UDP port used by the parent process.
        combo: User-facing hotkey combo string.

    Returns:
        Command argv for either the Swift helper or Python fallback helper.
    """
    from shokztype.core.hotkey_helper import _parse_combo

    helper_path = Path(app_dir) / "hotkey_helper"
    if helper_path.is_file():
        key_code, mod_mask = _parse_combo(combo)
        return [str(helper_path), str(port), str(key_code), str(mod_mask)]

    return [
        str(executable),
        "--hotkey-helper",
        "--port",
        str(port),
        "--combo",
        combo,
    ]


# ---------------------------------------------------------------------------
# PersistentKeyListener — singleton
# ---------------------------------------------------------------------------

class PersistentKeyListener:
    """Process-wide singleton key listener.

    On macOS frozen apps: spawns a helper subprocess for NSEvent listening.
    Otherwise: uses pynput Listener.
    """

    _instance: PersistentKeyListener | None = None

    def __init__(self) -> None:
        self._listener: keyboard.Listener | None = None
        self._lock = threading.Lock()
        self._hotkey: keyboard.HotKey | None = None
        self._hotkey_combo: str = ""
        self._hotkey_callback: Callable | None = None
        self._on_press_hook: Callable | None = None
        self._on_release_hook: Callable | None = None
        self._use_helper = IS_MACOS_FROZEN
        self._helper_proc: subprocess.Popen | None = None
        self._helper_port: int = 0
        self._helper_ctrl_port: int = 0
        self._recv_sock: socket.socket | None = None

    @classmethod
    def get(cls) -> PersistentKeyListener:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # --- Lifecycle ---

    def start(self) -> None:
        if self._use_helper:
            logger.info("持久键盘监听器: macOS 打包模式，将启动 helper 子进程")
            return
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
        logger.info("持久键盘监听器已启动 (pynput)")

    def start_helper(self, combo: str) -> None:
        """Spawn the hotkey helper subprocess (macOS frozen only)."""
        if not self._use_helper:
            return
        self._stop_helper()

        self._helper_port = _alloc_udp_port()
        self._recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._recv_sock.bind(("127.0.0.1", self._helper_port))
        self._recv_sock.settimeout(1.0)

        app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        log_dir = _runtime_log_dir(sys.executable)
        log_dir.mkdir(parents=True, exist_ok=True)
        helper_log = log_dir / "hotkey_helper.log"
        cmd = _helper_command(app_dir, sys.executable, self._helper_port, combo)

        self._helper_proc = subprocess.Popen(
            cmd,
            stdout=helper_log.open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        logger.info(
            "hotkey helper 已启动 (PID=%d, port=%d, combo=%s, cmd=%s)",
            self._helper_proc.pid,
            self._helper_port,
            combo,
            cmd[0],
        )

        threading.Thread(target=self._recv_loop, daemon=True, name="HotkeyRecv").start()

    def _stop_helper(self) -> None:
        if self._helper_proc is not None:
            if self._helper_ctrl_port:
                try:
                    msg = json.dumps({"cmd": "quit"}).encode()
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.sendto(msg, ("127.0.0.1", self._helper_ctrl_port))
                    s.close()
                    self._helper_proc.wait(timeout=2)
                except Exception:
                    pass
            try:
                self._helper_proc.terminate()
                self._helper_proc.wait(timeout=2)
            except Exception:
                try:
                    self._helper_proc.kill()
                except Exception:
                    pass
            self._helper_proc = None
            self._helper_ctrl_port = 0
        if self._recv_sock is not None:
            try:
                self._recv_sock.close()
            except Exception:
                pass
            self._recv_sock = None

    def update_helper_combo(self, combo: str) -> None:
        if self._helper_ctrl_port:
            try:
                msg = json.dumps({"cmd": "update_combo", "combo": combo}).encode()
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.sendto(msg, ("127.0.0.1", self._helper_ctrl_port))
                s.close()
            except Exception:
                pass

    def _recv_loop(self) -> None:
        while self._recv_sock is not None:
            try:
                data, _ = self._recv_sock.recvfrom(4096)
                msg = json.loads(data)
                if msg.get("event") == "hotkey":
                    logger.info("hotkey helper event received")
                    with self._lock:
                        cb = self._hotkey_callback
                    if cb is not None:
                        try:
                            cb()
                        except Exception:
                            logger.exception("hotkey callback failed")
                    else:
                        logger.warning("hotkey helper event ignored: callback is not set")
                elif msg.get("event") == "ready":
                    self._helper_ctrl_port = msg.get("ctrl_port", 0)
                    logger.info("hotkey helper ready (ctrl_port=%d)", self._helper_ctrl_port)
            except socket.timeout:
                continue
            except Exception:
                if self._recv_sock is None:
                    break
                logger.exception("hotkey helper receive loop failed")

    def cleanup(self) -> None:
        self._stop_helper()

    # --- Hotkey / hooks API ---

    def set_hotkey(self, combo: str, callback: Callable[[], None]) -> None:
        with self._lock:
            self._hotkey_combo = combo
            self._hotkey_callback = callback
            if not self._use_helper:
                normalized = _normalize_combo(combo)
                keys = keyboard.HotKey.parse(normalized)
                self._hotkey = keyboard.HotKey(keys, callback)
        logger.info("热键已设置: %s", combo)

    def clear_hotkey(self) -> None:
        with self._lock:
            self._hotkey = None
            self._hotkey_callback = None

    def set_hooks(
        self,
        on_press: Callable | None,
        on_release: Callable | None = None,
    ) -> None:
        with self._lock:
            self._on_press_hook = on_press
            self._on_release_hook = on_release

    def clear_hooks(self) -> None:
        with self._lock:
            self._on_press_hook = None
            self._on_release_hook = None

    # --- pynput callbacks (dev mode) ---

    def _canonical(self, key):
        if self._listener is not None:
            return self._listener.canonical(key)
        return key

    def _on_press(self, key) -> None:
        with self._lock:
            hook = self._on_press_hook
            hotkey = self._hotkey
        if hook is not None:
            hook(key)
            return
        if hotkey is not None:
            hotkey.press(self._canonical(key))

    def _on_release(self, key) -> None:
        with self._lock:
            hook = self._on_release_hook
            hotkey = self._hotkey
        if hook is not None:
            hook(key)
            return
        if hotkey is not None:
            hotkey.release(self._canonical(key))


def _alloc_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# HotkeyManager — CLI mode (creates its own GlobalHotKeys per combo)
# ---------------------------------------------------------------------------

class HotkeyManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listeners: dict[str, keyboard.GlobalHotKeys] = {}

    def register(self, combo: str, callback: Callable[[], None]) -> None:
        with self._lock:
            if combo in self._listeners:
                logger.warning("热键 %s 已注册，覆盖旧的回调", combo)
                self._listeners[combo].stop()

            normalized = _normalize_combo(combo)
            try:
                listener = keyboard.GlobalHotKeys({normalized: callback})
                listener.daemon = True
                listener.start()
            except Exception as exc:
                logger.error("注册热键 %s 失败: %s", combo, exc)
                raise

            self._listeners[combo] = listener
            logger.info("已注册热键 %s (pynput: %s)", combo, normalized)

    def unregister_all(self) -> None:
        with self._lock:
            for combo, listener in list(self._listeners.items()):
                listener.stop()
                logger.info("已移除热键 %s", combo)
            self._listeners.clear()

    def cleanup(self) -> None:
        self.unregister_all()
