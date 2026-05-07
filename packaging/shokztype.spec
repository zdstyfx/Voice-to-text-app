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

# ---------------------------------------------------------------------------
# 平台相关的 binaries 和 hidden imports
# ---------------------------------------------------------------------------

platform_binaries = []
platform_hiddenimports = []

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
    ],
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
        # modelscope 声纹模型
        "modelscope.models.audio.sv.DTDNN",
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
        "tkinter",
        "tkinter.test",
        "test",
    ],
    noarchive=False,
)

# ---------------------------------------------------------------------------
# PYZ + EXE
# ---------------------------------------------------------------------------

pyz = PYZ(a.pure)

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
    [],
    exclude_binaries=True,
    **exe_kwargs,
)

# ---------------------------------------------------------------------------
# COLLECT（文件夹分发模式）
# ---------------------------------------------------------------------------

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
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
