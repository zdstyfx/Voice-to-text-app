"""Shokz Type - Chinese voice-to-text."""

import os
import sys

__version__ = "0.1.0"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 打包后 exe 所在目录（只读资源：模型、静态文件）
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = PROJECT_ROOT

# 可写数据目录（配置、speaker_db、日志等）
# macOS 打包后 .app bundle 只读，需要用 Application Support
if getattr(sys, 'frozen', False) and sys.platform == "darwin":
    DATA_DIR = os.path.join(
        os.path.expanduser("~/Library/Application Support"), "ShokzType"
    )
    os.makedirs(DATA_DIR, exist_ok=True)
else:
    DATA_DIR = APP_DIR
