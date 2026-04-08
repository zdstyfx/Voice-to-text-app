"""Pytest configuration and fixtures for vocotype tests."""

import sys
from unittest.mock import MagicMock

# Mock heavy dependencies before any imports
sys.modules['fireredvad'] = MagicMock()
sys.modules['fireredvad.core'] = MagicMock()
sys.modules['fireredvad.core.constants'] = MagicMock()
sys.modules['torch'] = MagicMock()
sys.modules['torchaudio'] = MagicMock()
