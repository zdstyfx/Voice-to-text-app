# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Shokz Type (cross-platform).

Usage:
    cd packaging
    pyinstaller --clean --noconfirm shokztype.spec
"""

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # 项目根目录

# ---------------------------------------------------------------------------
# 平台检测
# ---------------------------------------------------------------------------

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

# ---------------------------------------------------------------------------
# 找到 site-packages 里的关键 DLL / 数据
# ---------------------------------------------------------------------------

if IS_WINDOWS:
    site_pkg = Path(sys.prefix) / "Lib" / "site-packages"
else:
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_pkg = Path(sys.prefix) / "lib" / py_ver / "site-packages"

# sherpa-onnx 原生库
sherpa_dir = site_pkg / "sherpa_onnx"

# fireredvad 预训练模型目录（安装在 site-packages/pretrained_models/ 下）
fireredvad_pretrained = site_pkg / "pretrained_models"

# ---------------------------------------------------------------------------
# 平台相关的 binaries 和 hidden imports
# ---------------------------------------------------------------------------

platform_binaries = []
platform_hiddenimports = []

# sherpa-onnx 通过 ctypes 加载原生库，PyInstaller 静态分析无法检测，需手动收集
# 隐患：sherpa_dir 原来只被声明但从未加入 binaries，打包后 sherpa_onnx 会因
# 找不到 .dll/.dylib 而在运行时 ImportError
if sherpa_dir.exists():
    if IS_WINDOWS:
        for _p in sherpa_dir.glob("*.dll"):
            platform_binaries.append((str(_p), "sherpa_onnx"))
    elif IS_MACOS:
        for _p in list(sherpa_dir.glob("*.dylib")) + list(sherpa_dir.glob("*.so")):
            platform_binaries.append((str(_p), "sherpa_onnx"))

if IS_WINDOWS:
    portaudio_dir = site_pkg / "_sounddevice_data" / "portaudio-binaries"
    platform_binaries.append(
        (str(portaudio_dir / "libportaudio64bit.dll"), "_sounddevice_data/portaudio-binaries"),
    )
    platform_hiddenimports.extend([
        "comtypes",
        "comtypes.stream",
        "pystray",
        "pystray._win32",
        "PIL",
        # 隐患修复：Windows 下 pywebview 使用 Edge WebView2 后端，
        # 动态选择 backend，PyInstaller 检测不到字符串拼接的 import
        "webview",
        "webview.platforms",
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
        # 隐患修复：pynput Windows 后端同样是动态 import，需手动声明
        "pynput._util.win32",
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        # 平台模块
        "shokztype.core.output_win",
        "shokztype.web.services.device_monitor_win",
    ])
elif IS_MACOS:
    platform_hiddenimports.extend([
        # pywebview macOS backend
        "webview",
        "webview.platforms",
        "webview.platforms.cocoa",
        # pynput macOS backend
        "pynput._util",
        "pynput._util.darwin",
        "pynput.keyboard._darwin",
        "pynput.mouse._darwin",
        # PyObjC frameworks
        "objc",
        "AppKit",
        "Foundation",
        "Quartz",
        "WebKit",
        "ApplicationServices",
        "CoreFoundation",
        "PyObjCTools",
        "PyObjCTools.AppHelper",
        "Security",
        "UniformTypeIdentifiers",
        # pywebview 额外依赖
        "bottle",
        "proxy_tools",
        # 平台模块
        "shokztype.core.output_mac",
        "shokztype.web.services.device_monitor_mac",
    ])

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

# fireredvad 预训练模型（路径逻辑：frozen 后 pkg_root 指向 _internal/，
# 所以模型需要打包到 _internal/pretrained_models/ 下）
extra_datas = []
if fireredvad_pretrained.exists():
    extra_datas.append((str(fireredvad_pretrained), "pretrained_models"))

a = Analysis(
    [str(ROOT / "shokztype" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=platform_binaries,
    datas=[
        # Web 静态文件
        (str(ROOT / "shokztype" / "web" / "static"), "shokztype/web/static"),
        # Overlay 子进程脚本
        (str(ROOT / "shokztype" / "web" / "services" / "overlay_process.py"), "shokztype/web/services"),
        # 配置模板
        (str(ROOT / "config.json.example"), "."),
        # KWS 关键词
        (str(ROOT / "keywords.txt"), "."),
        # 图标
        (str(ROOT / "shokztype" / "assets" / "shokztype.ico"), "shokztype/assets"),
        # librosa stub 文件（funasr_onnx 依赖）
        (str(site_pkg / "librosa" / "__init__.pyi"), "librosa"),
        (str(site_pkg / "librosa" / "core" / "__init__.pyi"), "librosa/core"),
        (str(site_pkg / "librosa" / "feature" / "__init__.pyi"), "librosa/feature"),
        (str(site_pkg / "librosa" / "util" / "__init__.pyi"), "librosa/util"),
    ] + extra_datas,
    hiddenimports=[
        # sounddevice + PortAudio
        "sounddevice",
        "_sounddevice_data",
        # Web 框架
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # ASR
        "funasr_onnx",
        "sherpa_onnx",
        # 隐患修复：fireredvad (VAD) 完全缺失于 spec，动态 import 无法被检测
        "fireredvad",
        "fireredvad.core",
        # 隐患修复：onnxruntime 原生库（funasr_onnx/fireredvad 共用）
        "onnxruntime",
        "onnxruntime.capi",
        "onnxruntime.capi.onnxruntime_inference_collection",
        # modelscope 声纹模型（动态 import 较多，尽量穷举已知子模块）
        "modelscope.models.audio.sv.DTDNN",
        "modelscope.models.audio.sv",
        "modelscope.pipelines",
        "modelscope.utils.hub",
        # 热键
        "pynput",
        "pynput.keyboard",
        "pynput.mouse",
        # 其他
        "librosa",
        "soundfile",
        "engineio.async_drivers.threading",
        # 平台检测
        "shokztype.core.platform",
    ] + platform_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "test",
    ],
    noarchive=False,
)

# ---------------------------------------------------------------------------
# PYZ + Splash（仅 Windows；macOS 不支持 PyInstaller splash screen）
# ---------------------------------------------------------------------------

pyz = PYZ(a.pure)

# Windows splash screen：exe 双击后立刻显示，Python 还没开始初始化时就可见。
# 代码里调用 pyi_splash.close() 来关闭（见 shokztype/__main__.py）。
# 依赖 PyInstaller 5.7+；如果版本太旧会在此处报 NameError，升级即可。
_splash_extras = []  # 供 EXE / COLLECT 引用
if IS_WINDOWS:
    _splash_img = Path(SPECPATH) / "splash.png"
    if _splash_img.exists():
        splash = Splash(
            str(_splash_img),
            binaries=a.binaries,
            datas=a.datas,
            text_pos=None,       # 不显示"正在加载 xxx.py"的进度文字，保持画面简洁
            minify_script=True,
            always_on_top=True,
        )
        _splash_extras = [splash, splash.binaries]
    else:
        import warnings
        warnings.warn(
            "splash.png 不存在，跳过 splash screen。"
            "运行 python packaging/create_splash.py 生成。"
        )

# ---------------------------------------------------------------------------
# EXE
# ---------------------------------------------------------------------------

exe_kwargs = dict(
    name="ShokzType",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

if IS_WINDOWS:
    exe_kwargs["icon"] = str(ROOT / "shokztype" / "assets" / "shokztype.ico")
elif IS_MACOS:
    exe_kwargs["target_arch"] = None  # universal

exe = EXE(
    pyz,
    a.scripts,
    *_splash_extras,   # splash + splash.binaries（Windows 有；macOS 空列表）
    [],
    exclude_binaries=True,
    **exe_kwargs,
)

# ---------------------------------------------------------------------------
# COLLECT（文件夹分发模式）
# ---------------------------------------------------------------------------

_collect_extras = []
if IS_WINDOWS and _splash_extras:
    _collect_extras = [_splash_extras[1]]  # splash.binaries

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    *_collect_extras,
    strip=False,
    upx=False,
    name="ShokzType",
)

# ---------------------------------------------------------------------------
# macOS .app bundle
# ---------------------------------------------------------------------------

if IS_MACOS:
    icns_path = ROOT / "shokztype" / "assets" / "shokztype.icns"
    app = BUNDLE(
        coll,
        name="ShokzType.app",
        icon=str(icns_path) if icns_path.exists() else None,
        bundle_identifier="com.shokz.shokztype",
        info_plist={
            "CFBundleName": "ShokzType",
            "CFBundleDisplayName": "Shokz Type",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSMicrophoneUsageDescription": "Shokz Type 需要麦克风权限来进行语音识别。",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
