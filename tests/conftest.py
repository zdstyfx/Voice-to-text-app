"""Pytest configuration and fixtures for vocotype tests."""

import sys
from unittest.mock import MagicMock

# Mock heavy dependencies before any imports
sys.modules['fireredvad'] = MagicMock()
sys.modules['fireredvad.core'] = MagicMock()
sys.modules['fireredvad.core.constants'] = MagicMock()
sys.modules['torch'] = MagicMock()
sys.modules['torchaudio'] = MagicMock()

# Mock platform-specific modules so tests run on any OS
if sys.platform != "win32":
    sys.modules['comtypes'] = MagicMock()
    sys.modules['ctypes.wintypes'] = MagicMock()

if sys.platform != "darwin":
    sys.modules['Quartz'] = MagicMock()
