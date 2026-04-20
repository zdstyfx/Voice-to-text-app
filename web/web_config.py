"""Web 层配置扩展。

在 VoiceInterface 原有 app.config 基础上，增加 LLM、Prompt、处理模式等 Web 专用字段。
"""

import json
import os
import threading
from typing import Any

from app.config import DEFAULT_CONFIG as APP_DEFAULT_CONFIG, _merge_dict

WEB_EXTRA_DEFAULTS: dict[str, Any] = {
    "currentMode": "translate",
    "llm": {
        "apiBaseUrl": "",
        "apiKey": "",
        "model": "",
        "timeoutSeconds": 90,
        "temperature": 0.2,
    },
    "translateTargetLanguage": "\u82f1\u8bed",
    "prompts": {
        "translate": (
            "#Role\n"
            "\u4f60\u662f\u4e00\u4e2a\u8bed\u97f3\u8f6c\u5199\u6587\u672c\u7684\u7ffb\u8bd1\u5de5\u5177\u3002\n\n"
            "#\u6838\u5fc3\u89c4\u5219\n"
            "1. \u7ffb\u8bd1\u4e3a{targetLanguage}\n"
            "2. \u76f4\u63a5\u8fd4\u56de\u8bd1\u6587\n\n"
            "#\u8f93\u5165\n{text}"
        ),
        "polish": (
            "#Role\n"
            "\u4f60\u662f\u4e00\u4e2a\u6587\u672c\u6574\u7406\u4e13\u5bb6\u3002\n\n"
            "#\u6838\u5fc3\u89c4\u5219\n"
            "1. \u5c06\u53e3\u8bed\u8f6c\u4e3a\u4e66\u9762\u8868\u8fbe\n"
            "2. \u76f4\u63a5\u8fd4\u56de\u6574\u7406\u540e\u7684\u6587\u672c\n\n"
            "#\u8f93\u5165\n{text}"
        ),
    },
    "voiceprint": {
        "enabled": False,
        "activeProfiles": [],
    },
    "wakeup": {
        "method": "hotkey",
        "hotkey": {"combo": "f2"},
        "vad": {"keyword": ""},
    },
}

DEFAULT_CONFIG = _merge_dict(APP_DEFAULT_CONFIG, WEB_EXTRA_DEFAULTS)

_lock = threading.RLock()
_config: dict[str, Any] | None = None
_config_path: str | None = None


def _resolve_config_path(path: str | None = None) -> str:
    if path:
        return os.path.abspath(path)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "config.json")


def load_config(path: str | None = None) -> dict[str, Any]:
    global _config, _config_path
    with _lock:
        _config_path = _resolve_config_path(path)
        if os.path.exists(_config_path):
            with open(_config_path, "r", encoding="utf-8") as f:
                overrides = json.load(f)
            _config = _merge_dict(DEFAULT_CONFIG, overrides)
        else:
            _config = dict(DEFAULT_CONFIG)
            _save_to_disk(_config, _config_path)
        return dict(_config)


def get_config() -> dict[str, Any]:
    with _lock:
        if _config is None:
            return load_config()
        return dict(_config)


def update_config(overrides: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        if _config is None:
            load_config()
        merged = _merge_dict(_config, overrides)
        _config.clear()
        _config.update(merged)
        _save_to_disk(_config, _config_path)
        return dict(_config)


def _save_to_disk(config: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
