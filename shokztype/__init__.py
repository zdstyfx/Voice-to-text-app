"""Shokz Type - Chinese voice-to-text for Windows."""

import os
import sys

__version__ = "0.1.0"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 打包后 exe 所在目录（分发根目录）
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = PROJECT_ROOT
