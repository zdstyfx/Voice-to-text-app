# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Shokz Type.

Usage:
    cd packaging
    pyinstaller shokztype.spec
"""

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # 项目根目录

# ---------------------------------------------------------------------------
# 找到 site-packages 里的关键 DLL / 数据
# ---------------------------------------------------------------------------

site_pkg = Path(sys.prefix) / "Lib" / "site-packages"

# PortAudio DLL（sounddevice 依赖）
portaudio_dir = site_pkg / "_sounddevice_data" / "portaudio-binaries"

# sherpa-onnx 原生库
sherpa_dir = site_pkg / "sherpa_onnx"

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

a = Analysis(
    [str(ROOT / "shokztype" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[
        # PortAudio
        (str(portaudio_dir / "libportaudio64bit.dll"), "_sounddevice_data/portaudio-binaries"),
    ],
    datas=[
        # Web 静态文件
        (str(ROOT / "shokztype" / "web" / "static"), "shokztype/web/static"),
        # Overlay 子进程脚本
        (str(ROOT / "shokztype" / "web" / "services" / "overlay_process.py"), "shokztype/web/services"),
        # 配置模板
        (str(ROOT / "config.json.example"), "."),
        # KWS 关键词
        (str(ROOT / "keywords.txt"), "."),
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
        # COM
        "comtypes",
        "comtypes.stream",
        # modelscope 声纹模型
        "modelscope.models.audio.sv.DTDNN",
        # 其他
        "keyboard",
        "librosa",
        "soundfile",
        "engineio.async_drivers.threading",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "PIL",
        "tkinter.test",
        "test",
    ],
    noarchive=False,
)

# ---------------------------------------------------------------------------
# PYZ + EXE
# ---------------------------------------------------------------------------

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ShokzType",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX 压缩有时会破坏 DLL
    console=True,  # 保留控制台便于调试，发布版改 False
    icon=None,  # 可以加 .ico 图标
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
