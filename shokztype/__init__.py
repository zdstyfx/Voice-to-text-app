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

# 可写数据目录（config.json、speaker_db.json、logs 等）
# 打包后安装目录可能是只读的（macOS .app bundle；Windows Program Files），
# 必须使用操作系统指定的用户可写目录。
if getattr(sys, 'frozen', False):
    if sys.platform == "darwin":
        DATA_DIR = os.path.join(
            os.path.expanduser("~/Library/Application Support"), "ShokzType"
        )
    elif sys.platform == "win32":
        # %LOCALAPPDATA% 在任何安装位置（包括 Program Files）下都可写
        _local_appdata = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
        DATA_DIR = os.path.join(_local_appdata, "ShokzType")
    else:
        DATA_DIR = APP_DIR
    os.makedirs(DATA_DIR, exist_ok=True)
else:
    DATA_DIR = APP_DIR
