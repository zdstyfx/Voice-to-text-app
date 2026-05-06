"""macOS 热键监听子进程。

使用 pynput.keyboard.Listener 监听全局键盘事件。
作为独立进程运行，通过 UDP 通知主进程热键触发。

启动方式（由主进程管理）：
    ShokzType --hotkey-helper --port <udp_port> --combo <combo_str>
"""

import json
import socket
import sys
import threading


def run_helper(port: int, combo: str):
    from pynput import keyboard

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    key_code, mod_mask = _parse_combo(combo)
    print(f"[hotkey-helper] combo={combo} keyCode={key_code} modMask={mod_mask:#x}", flush=True)

    pressed_modifiers = set()

    _MODIFIER_VKS = {
        55, 54,   # cmd, cmd_r
        56, 60,   # shift, shift_r
        59, 62,   # ctrl, ctrl_r
        58, 61,   # alt, alt_r
    }

    def on_press(key):
        vk = None
        if hasattr(key, 'vk') and key.vk is not None:
            vk = key.vk
        elif hasattr(key, 'value') and hasattr(key.value, 'vk'):
            vk = key.value.vk

        if vk in _MODIFIER_VKS:
            pressed_modifiers.add(vk)
            return

        current_mod = 0
        if pressed_modifiers & {59, 62}:
            current_mod |= 0x40000
        if pressed_modifiers & {58, 61}:
            current_mod |= 0x80000
        if pressed_modifiers & {56, 60}:
            current_mod |= 0x20000
        if pressed_modifiers & {55, 54}:
            current_mod |= 0x100000

        if vk == key_code and current_mod == mod_mask:
            msg = json.dumps({"event": "hotkey", "combo": combo})
            sock.sendto(msg.encode(), ("127.0.0.1", port))
            print(f"[hotkey-helper] HOTKEY TRIGGERED", flush=True)

    def on_release(key):
        vk = None
        if hasattr(key, 'vk') and key.vk is not None:
            vk = key.vk
        elif hasattr(key, 'value') and hasattr(key.value, 'vk'):
            vk = key.value.vk
        pressed_modifiers.discard(vk)

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    print(f"[hotkey-helper] pynput Listener started, port={port}", flush=True)

    # 通知主进程 ready
    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ctrl_sock.bind(("127.0.0.1", 0))
    ctrl_port = ctrl_sock.getsockname()[1]
    sock.sendto(json.dumps({"event": "ready", "ctrl_port": ctrl_port}).encode(),
                ("127.0.0.1", port))

    # 主循环：等待控制命令
    ctrl_sock.settimeout(1.0)
    while listener.is_alive():
        try:
            data, _ = ctrl_sock.recvfrom(4096)
            msg = json.loads(data)
            if msg.get("cmd") == "quit":
                listener.stop()
                break
        except socket.timeout:
            continue
        except Exception:
            continue


_MAC_KEYCODE_MAP = {
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    "space": 49, "escape": 53, "esc": 53, "tab": 48, "delete": 51,
    "return": 36, "enter": 36,
}
for _i, _c in enumerate("asdfhgzxcv\x00bqweryt123465=97-80]ou[ip\x00lj'k;\\,/nm."):
    if _c != "\x00":
        _MAC_KEYCODE_MAP[_c] = _i

_MAC_MOD_FLAGS = {"ctrl": 0x40000, "alt": 0x80000, "shift": 0x20000, "cmd": 0x100000}


def _parse_combo(combo: str) -> tuple[int, int]:
    parts = [p.strip().lower() for p in combo.split("+")]
    mod_mask = 0
    key_code = -1
    for p in parts:
        if p in ("ctrl", "control"):
            mod_mask |= _MAC_MOD_FLAGS["ctrl"]
        elif p in ("alt",):
            mod_mask |= _MAC_MOD_FLAGS["alt"]
        elif p in ("shift",):
            mod_mask |= _MAC_MOD_FLAGS["shift"]
        elif p in ("cmd", "command", "super", "win"):
            mod_mask |= _MAC_MOD_FLAGS["cmd"]
        else:
            key_code = _MAC_KEYCODE_MAP.get(p, -1)
    return key_code, mod_mask


if __name__ == "__main__":
    _port = 0
    _combo = "f2"
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--port" and i + 1 < len(args):
            _port = int(args[i + 1])
        elif a == "--combo" and i + 1 < len(args):
            _combo = args[i + 1]
    if _port:
        run_helper(_port, _combo)
