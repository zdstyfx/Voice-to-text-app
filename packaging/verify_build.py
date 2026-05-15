"""打包产物健康检查。

build.bat / build.sh 完成后运行：
    python verify_build.py            # 检查 Windows dist
    python verify_build.py --mac      # 检查 macOS dist
    python verify_build.py --verbose  # 显示完整路径

每个检查项标注 [PASS] / [WARN] / [FAIL]，最后给出汇总。
FAIL = 分发给用户后大概率崩溃；WARN = 可能在某些机器上出问题。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ─────────────────────────────────────────────
# 颜色（Windows 10+ 支持 ANSI；旧版降级）
# ─────────────────────────────────────────────
_USE_COLOR = sys.stdout.isatty() and (
    sys.platform != "win32" or os.environ.get("TERM") or os.environ.get("WT_SESSION")
)


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def green(t: str) -> str:
    return _c(t, "32")


def yellow(t: str) -> str:
    return _c(t, "33")


def red(t: str) -> str:
    return _c(t, "31")


# ─────────────────────────────────────────────
# 检查结果收集
# ─────────────────────────────────────────────

_results: list[tuple[str, str, str]] = []  # (level, name, detail)


def PASS(name: str, detail: str = "") -> None:
    _results.append(("PASS", name, detail))
    print(f"  {green('[PASS]')} {name}" + (f"  {detail}" if detail else ""))


def WARN(name: str, detail: str = "") -> None:
    _results.append(("WARN", name, detail))
    print(f"  {yellow('[WARN]')} {name}" + (f"\n         → {detail}" if detail else ""))


def FAIL(name: str, detail: str = "") -> None:
    _results.append(("FAIL", name, detail))
    print(f"  {red('[FAIL]')} {name}" + (f"\n         → {detail}" if detail else ""))


# ─────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────

def check_file(path: Path, name: str, level: str = "FAIL") -> bool:
    if path.is_file():
        PASS(name)
        return True
    (FAIL if level == "FAIL" else WARN)(name, f"缺失: {path}")
    return False


def check_dir(path: Path, name: str, level: str = "FAIL") -> bool:
    if path.is_dir():
        PASS(name)
        return True
    (FAIL if level == "FAIL" else WARN)(name, f"缺失: {path}")
    return False


def check_glob(parent: Path, pattern: str, name: str, level: str = "FAIL") -> list[Path]:
    matches = list(parent.glob(pattern))
    if matches:
        PASS(name, f"找到 {len(matches)} 个文件")
        return matches
    (FAIL if level == "FAIL" else WARN)(name, f"在 {parent} 中未找到 {pattern}")
    return []


# ─────────────────────────────────────────────
# 检查逻辑
# ─────────────────────────────────────────────

def check_windows(dist: Path, verbose: bool) -> None:
    internal = dist / "_internal"

    print("\n── 基础结构 ──")
    if not check_dir(dist, "dist/ShokzType 目录"):
        print("  无法继续，dist 目录不存在。")
        return
    check_file(dist / "ShokzType.exe", "ShokzType.exe 主程序")
    check_dir(internal, "_internal/ 目录")

    print("\n── 前端静态资源 ──")
    static = internal / "shokztype" / "web" / "static"
    check_dir(static, "shokztype/web/static/")
    check_file(static / "index.html", "static/index.html")
    check_dir(static / "assets", "static/assets/")

    print("\n── 图标 & 配置 ──")
    check_file(internal / "shokztype" / "assets" / "shokztype.ico", "shokztype.ico 图标")
    check_file(dist / "config.json", "config.json 配置文件")
    check_file(dist / "keywords.txt", "keywords.txt 关键词文件", level="WARN")

    print("\n── KWS 模型 ──")
    kws_dirs = list(dist.glob("sherpa-onnx-kws-*"))
    if kws_dirs:
        kd = kws_dirs[0]
        PASS("KWS 模型目录", str(kd.name))
        check_file(kd / "tokens.txt", "kws tokens.txt")
    else:
        WARN("KWS 模型目录", "未找到 sherpa-onnx-kws-* 目录（热词唤醒不可用）")

    print("\n── Python 核心包 ──")
    for pkg in ["shokztype", "fastapi", "uvicorn", "pynput", "sounddevice", "librosa"]:
        check_dir(internal / pkg, f"_internal/{pkg}/")

    print("\n── sherpa_onnx 原生库（ctypes 加载）──")
    # 这是最常见的漏打包问题：sherpa_dir 原来只被声明，从未加入 binaries
    sherpa_pkg = internal / "sherpa_onnx"
    if check_dir(sherpa_pkg, "_internal/sherpa_onnx/", level="FAIL"):
        dlls = list(sherpa_pkg.glob("*.dll"))
        if dlls:
            PASS("sherpa_onnx *.dll 原生库", f"找到 {len(dlls)} 个 DLL")
            if verbose:
                for d in dlls:
                    print(f"    {d.name}")
        else:
            FAIL("sherpa_onnx *.dll 原生库",
                 "目录存在但无 .dll 文件——关键词唤醒会在运行时 crash")

    print("\n── onnxruntime（funasr / fireredvad 共用）──")
    ort_dir = internal / "onnxruntime"
    if ort_dir.is_dir():
        PASS("_internal/onnxruntime/")
    else:
        # 有时以 .pyd 或 DLL 形式出现
        ort_files = list(internal.glob("onnxruntime*.dll")) + list(internal.glob("onnxruntime*.pyd"))
        if ort_files:
            PASS("onnxruntime 原生库", f"找到 {len(ort_files)} 个文件")
        else:
            WARN("onnxruntime", "未找到 onnxruntime——本地 ASR/VAD 可能无法初始化")

    print("\n── fireredvad & 预训练模型 ──")
    check_dir(internal / "fireredvad", "_internal/fireredvad/", level="WARN")
    vad_model = internal / "pretrained_models" / "FireRedVAD" / "Stream-VAD"
    if vad_model.is_dir():
        PASS("fireredvad Stream-VAD 模型")
    else:
        WARN("fireredvad Stream-VAD 模型",
             "VAD 模型未打包（若用 hotkey 唤醒可忽略；VAD+KWS 模式会失败）")

    print("\n── pywebview（Windows 桌面窗口）──")
    webview_dir = internal / "webview"
    if check_dir(webview_dir, "_internal/webview/", level="FAIL"):
        edgechromium = webview_dir / "platforms" / "edgechromium.py"
        winforms = webview_dir / "platforms" / "winforms.py"
        if edgechromium.is_file():
            PASS("webview/platforms/edgechromium.py（Win10+ Edge WebView2）")
        elif winforms.is_file():
            PASS("webview/platforms/winforms.py（Win7 兼容后端）")
        else:
            FAIL("webview Windows 后端",
                 "edgechromium.py / winforms.py 均缺失——桌面窗口无法显示")

    print("\n── pynput Windows 后端 ──")
    kb_win32 = internal / "pynput" / "keyboard" / "_win32.py"
    ms_win32 = internal / "pynput" / "mouse" / "_win32.py"
    check_file(kb_win32, "pynput/keyboard/_win32.py（全局热键）")
    check_file(ms_win32, "pynput/mouse/_win32.py", level="WARN")

    print("\n── overlay 子进程脚本 ──")
    overlay = internal / "shokztype" / "web" / "services" / "overlay_process.py"
    check_file(overlay, "overlay_process.py（状态浮窗）")


def check_macos(dist: Path, app: Path, verbose: bool) -> None:
    internal = dist / "_internal"

    print("\n── 基础结构 ──")
    check_dir(dist, "dist/ShokzType 目录")
    check_dir(app, "dist/ShokzType.app bundle")

    print("\n── .app bundle 内部 ──")
    macos_dir = app / "Contents" / "MacOS"
    check_dir(macos_dir, "Contents/MacOS/")
    check_file(macos_dir / "ShokzType", "ShokzType 主程序")
    check_file(macos_dir / "hotkey_helper", "hotkey_helper Swift 二进制", level="WARN")

    print("\n── 静态资源 & 配置 ──")
    static = internal / "shokztype" / "web" / "static"
    check_dir(static, "shokztype/web/static/")
    check_file(static / "index.html", "static/index.html")
    check_file(macos_dir / "config.json", ".app config.json")
    check_file(macos_dir / "keywords.txt", ".app keywords.txt", level="WARN")

    print("\n── sherpa_onnx 原生库 ──")
    sherpa_pkg = internal / "sherpa_onnx"
    if check_dir(sherpa_pkg, "_internal/sherpa_onnx/"):
        libs = list(sherpa_pkg.glob("*.dylib")) + list(sherpa_pkg.glob("*.so"))
        if libs:
            PASS("sherpa_onnx 原生库", f"找到 {len(libs)} 个文件")
        else:
            FAIL("sherpa_onnx 原生库",
                 "目录存在但无 .dylib/.so——关键词唤醒会在运行时 crash")

    print("\n── fireredvad & VAD 模型 ──")
    check_dir(internal / "fireredvad", "_internal/fireredvad/", level="WARN")
    vad_model = internal / "pretrained_models" / "FireRedVAD" / "Stream-VAD"
    if vad_model.is_dir():
        PASS("fireredvad Stream-VAD 模型")
    else:
        WARN("fireredvad Stream-VAD 模型", "VAD 模型未打包（hotkey 唤醒模式不受影响）")

    print("\n── pywebview macOS 后端 ──")
    webview_dir = internal / "webview"
    if check_dir(webview_dir, "_internal/webview/"):
        check_file(webview_dir / "platforms" / "cocoa.py", "webview/platforms/cocoa.py")

    print("\n── pynput macOS 后端 ──")
    check_file(internal / "pynput" / "keyboard" / "_darwin.py", "pynput/keyboard/_darwin.py")


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="ShokzType 打包产物健康检查")
    parser.add_argument("--mac", action="store_true", help="检查 macOS 产物（默认 Windows）")
    parser.add_argument("--dist", default=None, help="指定 dist 目录路径")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    if args.dist:
        dist = Path(args.dist)
    else:
        dist = script_dir / "dist" / "ShokzType"

    print("=" * 55)
    print("  ShokzType 打包产物健康检查")
    print(f"  检查目录: {dist}")
    print("=" * 55)

    if args.mac:
        app = script_dir / "dist" / "ShokzType.app"
        check_macos(dist, app, args.verbose)
    else:
        check_windows(dist, args.verbose)

    # 汇总
    passes = sum(1 for r in _results if r[0] == "PASS")
    warns = sum(1 for r in _results if r[0] == "WARN")
    fails = sum(1 for r in _results if r[0] == "FAIL")
    total = len(_results)

    print("\n" + "=" * 55)
    print(f"  结果: {green(f'{passes} PASS')}  {yellow(f'{warns} WARN')}  {red(f'{fails} FAIL')}  / {total} 项")
    if fails == 0 and warns == 0:
        print(f"  {green('✓ 全部通过，可以分发')}")
    elif fails == 0:
        print(f"  {yellow('△ 有警告，请确认是否影响目标用户')}")
    else:
        print(f"  {red('✗ 存在关键问题，建议修复后再分发')}")
    print("=" * 55)

    return 1 if fails > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
